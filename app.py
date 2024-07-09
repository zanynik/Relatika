from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from collections import Counter
import re
import os
import time
import random
from pathlib import Path

THIS_FOLDER = Path(__file__).parent.resolve()
users_table = THIS_FOLDER / "users.db"

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

def get_db_connection():
    retries = 5
    while retries > 0:
        try:
            conn = sqlite3.connect(users_table, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError as e:
            if 'database is locked' in str(e):
                time.sleep(1)
                retries -= 1
            else:
                raise e
    raise Exception("Database is locked for too long, giving up.")

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('home.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return render_template('dashboard.html', username=user['username'])

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        name = request.form['name']
        age = request.form['age']
        gender = request.form['gender']
        looking_for = request.form.getlist('looking_for')
        location = request.form['location']

        if not username or not password or not name or not age or not gender or not location:
            return render_template('register.html', error="Please fill in all required fields")

        conn = get_db_connection()
        existing_user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if existing_user:
            conn.close()
            return render_template('register.html', error="Username already exists")

        conn.execute('INSERT INTO users (username, password, name, age, gender, looking_for, location) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                     (username, generate_password_hash(password), name, age, gender, ','.join(looking_for), location))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user:
            if user['password'] == password:
                session['user_id'] = user['id']
                conn.close()
                return redirect(url_for('profile'))
            else:
                conn.close()
                return 'Invalid password'
        else:
            # Create a new user
            conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
            conn.commit()
            user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            session['user_id'] = user['id']
            conn.close()
            return redirect(url_for('profile'))
    else:
        return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('home'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    if request.method == 'POST':
        name = request.form['name']
        age = request.form['age']
        gender = request.form['gender']
        looking_for = ','.join(request.form.getlist('looking_for'))
        location = request.form['location']
        about = request.form['about']
        email = request.form['email']
        tel = request.form['tel']
        instagram = request.form['instagram']
        telegram = request.form['telegram']
        
        conn.execute('UPDATE users SET name = ?, age = ?, gender = ?, looking_for = ?, location = ?, about = ?, email = ?, tel = ?, instagram = ?, telegram = ? WHERE id = ?', 
                     (name, age, gender, looking_for, location, about, email, tel, instagram, telegram, user_id))
        conn.commit()
        
        photos = request.files.getlist('photos')
        for photo in photos:
            if photo.filename != '':
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], photo.filename)
                photo.save(photo_path)
                conn.execute('INSERT INTO photos (user_id, filename) VALUES (?, ?)', (user_id, photo.filename))
                conn.commit()

    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    locations = ['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix']  # Example locations
    user_photos = conn.execute('SELECT filename FROM photos WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()
    return render_template('profile.html', user_name=user['name'], user_age=user['age'], user_gender=user['gender'], 
                           user_looking_for=user['looking_for'] or '', user_location=user['location'], user_about=user['about'] or '',
                           user_email=user['email'] or '', user_tel=user['tel'] or '', user_instagram=user['instagram'] or '', user_telegram=user['telegram'] or '',
                           locations=locations, user_photos=user_photos)

@app.route('/browse')
def browse():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    users = conn.execute('SELECT id, name, age, location, about FROM users').fetchall()
    users_list = [dict(user) for user in users]

    # Fetch photos for each user
    for user in users_list:
        photo = conn.execute('SELECT filename FROM photos WHERE user_id = ?', (user['id'],)).fetchone()
        user['photo'] = photo['filename'] if photo else None

    conn.close()

    # Shuffle the list of users
    random.shuffle(users_list)

    return render_template('browse.html', users=users_list)

@app.route('/saved')
def saved():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    
    # Fetch profiles the user has interacted with
    photo_reveals = conn.execute('SELECT requestee_id as user_id FROM photo_reveals WHERE requester_id = ?', (user_id,)).fetchall()
    contact_shares = conn.execute('SELECT requestee_id as user_id FROM contact_shares WHERE requester_id = ?', (user_id,)).fetchall()
    heart_likes = conn.execute('SELECT profile_id as user_id FROM saved_profiles WHERE user_id = ?', (user_id,)).fetchall()
    saved_profiles = list({row['user_id'] for row in photo_reveals + contact_shares + heart_likes})

    if saved_profiles:
        placeholders = ', '.join(['?'] * len(saved_profiles))
        users = conn.execute(f'SELECT id, name, age, location, about FROM users WHERE id IN ({placeholders})', tuple(saved_profiles)).fetchall()
        users_list = [dict(user) for user in users]

        for user in users_list:
            photo = conn.execute('SELECT filename FROM photos WHERE user_id = ?', (user['id'],)).fetchone()
            user['photo'] = photo['filename'] if photo else None

        random.shuffle(users_list)
    else:
        users_list = []

    conn.close()
    return render_template('saved.html', users=users_list)

@app.route('/save_profile/<int:profile_id>', methods=['POST'])
def save_profile(profile_id):
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'})

    user_id = session['user_id']
    conn = get_db_connection()
    try:
        saved = conn.execute('SELECT 1 FROM saved_profiles WHERE user_id = ? AND profile_id = ?', (user_id, profile_id)).fetchone()
        if saved:
            conn.execute('DELETE FROM saved_profiles WHERE user_id = ? AND profile_id = ?', (user_id, profile_id))
            message = 'Profile unsaved successfully'
        else:
            conn.execute('INSERT INTO saved_profiles (user_id, profile_id) VALUES (?, ?)', (user_id, profile_id))
            message = 'Profile saved successfully'
        conn.commit()
    except Exception as e:
        print(f"Error saving profile {profile_id} for user {user_id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to save/unsave profile'})
    finally:
        conn.close()

    return jsonify({'status': 'success', 'message': message})


@app.route('/delete_photo/<filename>', methods=['POST'])
def delete_photo(filename):
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'})

    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute('DELETE FROM photos WHERE user_id = ? AND filename = ?', (user_id, filename))
    conn.commit()
    conn.close()

    photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(photo_path):
        os.remove(photo_path)

    return jsonify({'status': 'success'})

@app.route('/matches')
def matches():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    current_user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    all_users = conn.execute('SELECT * FROM users WHERE id != ?', (user_id,)).fetchall()

    current_user_words = re.findall(r'\w+', (current_user['about'] or '').lower())
    current_user_word_counts = Counter(current_user_words)

    match_list = []
    for user in all_users:
        user_words = re.findall(r'\w+', (user['about'] or '').lower())
        user_word_counts = Counter(user_words)
        matches = sum((current_user_word_counts & user_word_counts).values())
        total_words = len(set(current_user_words + user_words))
        match_percentage = (matches / total_words) * 100 if total_words > 0 else 0
        user_photo = conn.execute('SELECT filename FROM photos WHERE user_id = ?', (user['id'],)).fetchone()

        # Check if the profile is saved
        saved = conn.execute('SELECT 1 FROM saved_profiles WHERE user_id = ? AND profile_id = ?', (user_id, user['id'])).fetchone()

        match_list.append({
            'username': user['username'],
            'name': user['name'],
            'match_percentage': round(match_percentage, 2),
            'user_id': user['id'],
            'photo': user_photo['filename'] if user_photo else None,
            'about_glimpse': ' '.join((user['about'] or '').split()[:10]) + '...',
            'saved': bool(saved)
        })

    conn.close()
    match_list.sort(key=lambda x: x['match_percentage'], reverse=True)

    return render_template('matches.html', matches=match_list)

@app.route('/view_profile/<int:user_id>', methods=['GET', 'POST'])
def view_profile(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user_id = session['user_id']
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    user_photos = conn.execute('SELECT filename FROM photos WHERE user_id = ?', (user_id,)).fetchall()

    # Check photo reveal status
    photo_reveal = conn.execute('SELECT status FROM photo_reveals WHERE requester_id = ? AND requestee_id = ?', 
                                (current_user_id, user_id)).fetchone()
    photo_reveal_status = photo_reveal['status'] if photo_reveal else 'none'

    # Check contact share status
    contact_share = conn.execute('SELECT status FROM contact_shares WHERE requester_id = ? AND requestee_id = ?', 
                                (current_user_id, user_id)).fetchone()
    contact_share_status = contact_share['status'] if contact_share else 'none'

    conn.close()
    return render_template('view_profile.html', user_id=user_id, user_name=user['name'], user_age=user['age'], user_gender=user['gender'], 
                           user_location=user['location'], user_about=user['about'], user_email=user['email'] or '', 
                           user_tel=user['tel'] or '', user_instagram=user['instagram'] or '', user_telegram=user['telegram'] or '', 
                           user_photos=user_photos, photo_reveal_status=photo_reveal_status, contact_share_status=contact_share_status)

@app.route('/send_photo_reveal_request/<int:user_id>', methods=['POST'])
def send_photo_reveal_request(user_id):
    if 'user_id' not in session:
        print("User is not logged in")
        return jsonify({'status': 'error', 'message': 'Unauthorized'})

    current_user_id = session['user_id']
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO photo_reveals (requester_id, requestee_id) VALUES (?, ?)', (current_user_id, user_id))
        conn.commit()
        print("Photo reveal request sent from user_id:", current_user_id, "to user_id:", user_id)
    except Exception as e:
        print("Error sending photo reveal request:", e)
        return jsonify({'status': 'error', 'message': 'Failed to send request'})
    finally:
        conn.close()

    return jsonify({'status': 'success', 'message': 'Photo reveal request sent'})

@app.route('/send_contact_share_request/<int:user_id>', methods=['POST'])
def send_contact_share_request(user_id):
    if 'user_id' not in session:
        print("User is not logged in")
        return jsonify({'status': 'error', 'message': 'Unauthorized'})

    current_user_id = session['user_id']
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO contact_shares (requester_id, requestee_id) VALUES (?, ?)', (current_user_id, user_id))
        conn.commit()
        print("Contact share request sent from user_id:", current_user_id, "to user_id:", user_id)
    except Exception as e:
        print("Error sending contact share request:", e)
        return jsonify({'status': 'error', 'message': 'Failed to send request'})
    finally:
        conn.close()

    return jsonify({'status': 'success', 'message': 'Contact share request sent'})

@app.route('/handle_photo_share_request/<int:request_id>/<action>', methods=['POST'])
def handle_photo_share_request(request_id, action):
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'})

    user_id = session['user_id']
    conn = get_db_connection()
    try:
        if action == 'accept':
            conn.execute('UPDATE photo_reveals SET status = ?, message = ? WHERE id = ?', ('accepted', None, request_id))
            requester_id = conn.execute('SELECT requester_id FROM photo_reveals WHERE id = ?', (request_id,)).fetchone()['requester_id']
            conn.execute('INSERT INTO photo_reveals (requester_id, requestee_id, status) VALUES (?, ?, ?)', (user_id, requester_id, 'accepted'))
            message = f"Your photo reveal request to user {user_id} has been accepted."
            conn.execute('UPDATE photo_reveals SET message = ? WHERE requester_id = ? AND requestee_id = ?', (message, requester_id, user_id))
        elif action == 'decline':
            conn.execute('UPDATE photo_reveals SET status = ?, message = ? WHERE id = ?', ('declined', None, request_id))
            requester_id = conn.execute('SELECT requester_id FROM photo_reveals WHERE id = ?', (request_id,)).fetchone()['requester_id']
            message = f"Your photo reveal request to user {user_id} has been declined."
            conn.execute('UPDATE photo_reveals SET message = ? WHERE requester_id = ? AND requestee_id = ?', (message, requester_id, user_id))
        conn.commit()
    except Exception as e:
        print(f"Error handling photo reveal request {action}: {e}")
        return jsonify({'status': 'error', 'message': f'Failed to {action} request'})
    finally:
        conn.close()

    return jsonify({'status': 'success'})

@app.route('/handle_contact_share_request/<int:request_id>/<action>', methods=['POST'])
def handle_contact_share_request(request_id, action):
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'})

    user_id = session['user_id']
    conn = get_db_connection()
    try:
        if action == 'accept':
            conn.execute('UPDATE contact_shares SET status = ?, message = ? WHERE id = ?', ('accepted', None, request_id))
            requester_id = conn.execute('SELECT requester_id FROM contact_shares WHERE id = ?', (request_id,)).fetchone()['requester_id']
            conn.execute('INSERT INTO contact_shares (requester_id, requestee_id, status) VALUES (?, ?, ?)', (user_id, requester_id, 'accepted'))
            message = f"Your contact share request to user {user_id} has been accepted."
            conn.execute('UPDATE contact_shares SET message = ? WHERE requester_id = ? AND requestee_id = ?', (message, requester_id, user_id))
        elif action == 'decline':
            conn.execute('UPDATE contact_shares SET status = ?, message = ? WHERE id = ?', ('declined', None, request_id))
            requester_id = conn.execute('SELECT requester_id FROM contact_shares WHERE id = ?', (request_id,)).fetchone()['requester_id']
            message = f"Your contact share request to user {user_id} has been declined."
            conn.execute('UPDATE contact_shares SET message = ? WHERE requester_id = ? AND requestee_id = ?', (message, requester_id, user_id))
        conn.commit()
    except Exception as e:
        print(f"Error handling contact share request {action}: {e}")
        return jsonify({'status': 'error', 'message': f'Failed to {action} request'})
    finally:
        conn.close()

    return jsonify({'status': 'success'})

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    # Get photo reveal requests sent to the current user
    photo_reveals = conn.execute('''
        SELECT photo_reveals.id as request_id, users.username, photo_reveals.status 
        FROM photo_reveals 
        JOIN users ON photo_reveals.requester_id = users.id 
        WHERE photo_reveals.requestee_id = ? AND photo_reveals.status = 'pending'
    ''', (user_id,)).fetchall()

    # Get contact share requests sent to the current user
    contact_shares = conn.execute('''
        SELECT contact_shares.id as request_id, users.username, contact_shares.status 
        FROM contact_shares 
        JOIN users ON contact_shares.requester_id = users.id 
        WHERE contact_shares.requestee_id = ? AND contact_shares.status = 'pending'
    ''', (user_id,)).fetchall()

    photo_reveal_notifications = conn.execute('SELECT message, id FROM photo_reveals WHERE requester_id = ? AND message IS NOT NULL ORDER BY id DESC', (user_id,)).fetchall()
    contact_share_notifications = conn.execute('SELECT message, id FROM contact_shares WHERE requester_id = ? AND message IS NOT NULL ORDER BY id DESC', (user_id,)).fetchall()
    notifications = photo_reveal_notifications + contact_share_notifications
    notifications.sort(key=lambda x: x['id'], reverse=True)
    conn.close()
    return render_template('notifications.html', notifications=notifications,photo_reveals=photo_reveals, contact_shares=contact_shares)

@app.context_processor
def inject_notification_count():
    if 'user_id' in session:
        user_id = session['user_id']
        conn = get_db_connection()
        photo_reveal_count = conn.execute('SELECT COUNT(*) FROM photo_reveals WHERE requestee_id = ? AND status = "pending"', (user_id,)).fetchone()[0]
        contact_share_count = conn.execute('SELECT COUNT(*) FROM contact_shares WHERE requestee_id = ? AND status = "pending"', (user_id,)).fetchone()[0]
        photo_reveal_sent_count = conn.execute('SELECT COUNT(*) FROM photo_reveals WHERE requester_id = ? AND status <> "pending"', (user_id,)).fetchone()[0]
        contact_share_sent_count = conn.execute('SELECT COUNT(*) FROM contact_shares WHERE requester_id = ? AND status <> "pending"', (user_id,)).fetchone()[0]
        conn.close()
        return {'notification_count': photo_reveal_count + contact_share_count + photo_reveal_sent_count + contact_share_sent_count }
    return {'notification_count': 0}

if __name__ == '__main__':
    app.run(debug=True)

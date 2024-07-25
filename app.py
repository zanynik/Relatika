from flask import Flask, render_template, request, redirect, url_for, session, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
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

@app.before_request
def load_user():
    user_id = session.get('user_id')
    if user_id:
        conn = get_db_connection()
        g.user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        
        # Load matches
        all_users = conn.execute('SELECT * FROM users WHERE id != ?', (user_id,)).fetchall()

        current_user_words = re.findall(r'\w+', (g.user['about'] or '').lower())
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
                'age' : user['age'],
                'location' : user['location'],
                'match_percentage': round(match_percentage, 2),
                'user_id': user['id'],
                'photo': user_photo['filename'] if user_photo else None,
                'about_glimpse': ' '.join((user['about'] or '').split()[:10]) + '...',
                'saved': bool(saved)
            })
 
        match_list.sort(key=lambda x: x['match_percentage'], reverse=True)
        g.matches = match_list

        # Load saved profiles
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
        g.saved_profiles = users_list
        
        # Load Notifications
        photo_reveal_count = conn.execute('SELECT COUNT(*) FROM photo_reveals WHERE requestee_id = ? AND status = "pending"', (user_id,)).fetchone()[0]
        contact_share_count = conn.execute('SELECT COUNT(*) FROM contact_shares WHERE requestee_id = ? AND status = "pending"', (user_id,)).fetchone()[0]
        photo_reveal_sent_count = conn.execute('SELECT COUNT(*) FROM photo_reveals WHERE requester_id = ? AND status <> "pending" AND message != "Acknowledged"', (user_id,)).fetchone()[0]
        contact_share_sent_count = conn.execute('SELECT COUNT(*) FROM contact_shares WHERE requester_id = ? AND status <> "pending" AND message != "Acknowledged"', (user_id,)).fetchone()[0]

        g.notification_count = int(photo_reveal_count + contact_share_count + photo_reveal_sent_count + contact_share_sent_count)
        conn.close()
    else:
        g.user = None
        g.matches = []
        g.saved_profiles = []
        g.notification_count = 0

@app.context_processor
def inject_user():
    return dict(user=g.user, matches=g.matches, saved_profiles=g.saved_profiles,notification_count = g.notification_count)

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
        confirm_password = request.form['confirm_password']
        name = request.form['name']
        age = request.form['age']
        gender = request.form['gender']
        looking_for = request.form.getlist('looking_for')
        location = request.form['location']
        latitude = request.form['latitude']
        longitude = request.form['longitude']

        if not username or not password or not name or not age or not gender or not location or not latitude or not longitude:
            return render_template('register.html', error="Please fill in all required fields")

        if password != confirm_password:
            return render_template('register.html', error="Passwords do not match")
        
        if len(password) < 8 or not any(char.isdigit() for char in password) or not any(char.isupper() for char in password):
            return render_template('register.html', error="Password must be at least 8 characters long and include at least one number and one uppercase letter.")
        
        conn = get_db_connection()
        existing_user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if existing_user:
            conn.close()
            return render_template('register.html', error="Username already exists")

        conn.execute('INSERT INTO users (username, password, name, age, gender, looking_for, location, latitude, longitude) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', 
                     (username, generate_password_hash(password), name, age, gender, ','.join(looking_for), location, latitude, longitude))
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
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            conn.close()
            return redirect(url_for('ai_suggestions'))
        else:
            conn.close()
            error = 'Invalid username or password'
            return render_template('login.html', error=error)
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
        latitude = request.form['latitude']
        longitude = request.form['longitude']
        about = request.form['about']
        email = request.form['email']
        tel = request.form['tel']
        instagram = request.form['instagram']
        telegram = request.form['telegram']
        
        conn.execute('UPDATE users SET name = ?, age = ?, gender = ?, looking_for = ?, location = ?, latitude = ?, longitude = ?, about = ?, email = ?, tel = ?, instagram = ?, telegram = ? WHERE id = ?', 
                     (name, age, gender, looking_for, location, latitude, longitude, about, email, tel, instagram, telegram, user_id))
        conn.commit()
        
        photos = request.files.getlist('photos')
        for photo in photos:
            if photo.filename != '':
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], photo.filename)
                photo.save(photo_path)
                conn.execute('INSERT INTO photos (user_id, filename) VALUES (?, ?)', (user_id, photo.filename))
                conn.commit()

        return jsonify(status='success')

    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    user_photos = conn.execute('SELECT filename FROM photos WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()
    return render_template('profile.html', user_name=user['name'], user_age=user['age'], user_gender=user['gender'], 
                           user_looking_for=user['looking_for'] or '', user_location=user['location'], user_latitude=user['latitude'], user_longitude=user['longitude'],
                           user_about=user['about'] or '', user_email=user['email'] or '', user_tel=user['tel'] or '', user_instagram=user['instagram'] or '', user_telegram=user['telegram'] or '',
                           user_photos=user_photos)

@app.route('/browse')
def browse():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    user = conn.execute('SELECT id, name, age, location, about FROM users ORDER BY RANDOM() LIMIT 1').fetchone()
    # Fetch photos for random user
    user_photos = conn.execute('SELECT filename FROM photos WHERE user_id = ?', (user['id'],)).fetchall()
    conn.close()

    return render_template('browse.html', user=user, user_photos=user_photos)

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

@app.route('/next_random_profile')
def next_random_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if 'matches' in g and isinstance(g.matches, list):
        match_ids = [match['user_id'] for match in g.matches]
        if match_ids:
            random.shuffle(match_ids)
            return jsonify({'user_id': match_ids[0]})

@app.route('/send_superlike/<int:user_id>', methods=['POST'])
def send_superlike(user_id):
    send_photo_reveal_request(user_id)
    send_contact_share_request(user_id)
    return jsonify(status='success', message='Superlike sent.')

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
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    user_name=user['name']
    try:
        if action == 'accept':
            conn.execute('UPDATE photo_reveals SET status = ?, message = ? WHERE id = ?', ('accepted', None, request_id))
            requester_id = conn.execute('SELECT requester_id FROM photo_reveals WHERE id = ?', (request_id,)).fetchone()['requester_id']
            conn.execute('INSERT INTO photo_reveals (requester_id, requestee_id, status) VALUES (?, ?, ?)', (user_id, requester_id, 'accepted'))
            message = f"Your photo reveal request to user {user_name} has been accepted."
            conn.execute('UPDATE photo_reveals SET message = ? WHERE requester_id = ? AND requestee_id = ?', (message, requester_id, user_id))
        elif action == 'decline':
            conn.execute('UPDATE photo_reveals SET status = ?, message = ? WHERE id = ?', ('declined', None, request_id))
            requester_id = conn.execute('SELECT requester_id FROM photo_reveals WHERE id = ?', (request_id,)).fetchone()['requester_id']
            message = f"Your photo reveal request to user {user_name} has been declined."
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

@app.route('/acknowledge_notification/<int:notification_id>/<string:notification_type>', methods=['POST'])
def acknowledge_notification(notification_id, notification_type):
    if 'user_id' not in session:
        return jsonify(status='error', message='Unauthorized'), 401

    user_id = session['user_id']
    conn = get_db_connection()
    
    # Attempt to update the notification message to "Acknowledged"
    try:
        if notification_type == 'photo':
            conn.execute('UPDATE photo_reveals SET message = "Acknowledged" WHERE id = ? AND requester_id = ?', (notification_id, user_id))
        elif notification_type == 'contact':
            conn.execute('UPDATE contact_shares SET message = "Acknowledged" WHERE id = ? AND requester_id = ?', (notification_id, user_id))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify(status='error', message=str(e)), 500
    
    conn.close()
    return jsonify(status='success')

@app.route('/notification_count')
def notification_count():
    if 'user_id' not in session:
        return jsonify(count=0)

    user_id = session['user_id']
    conn = get_db_connection()
    photo_reveal_count = conn.execute('SELECT COUNT(*) FROM photo_reveals WHERE requestee_id = ? AND status = "pending"', (user_id,)).fetchone()[0]
    contact_share_count = conn.execute('SELECT COUNT(*) FROM contact_shares WHERE requestee_id = ? AND status = "pending"', (user_id,)).fetchone()[0]
    photo_reveal_sent_count = conn.execute('SELECT COUNT(*) FROM photo_reveals WHERE requester_id = ? AND status <> "pending" AND message != "Acknowledged"', (user_id,)).fetchone()[0]
    contact_share_sent_count = conn.execute('SELECT COUNT(*) FROM contact_shares WHERE requester_id = ? AND status <> "pending" AND message != "Acknowledged"', (user_id,)).fetchone()[0]
    conn.close()
    
    total_count = photo_reveal_count + contact_share_count + photo_reveal_sent_count + contact_share_sent_count
    return jsonify(count=total_count)

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    # Get photo reveal requests sent to the current user
    photo_reveals = conn.execute('''
        SELECT photo_reveals.requester_id, users.username, users.name, photo_reveals.status 
        FROM photo_reveals 
        JOIN users ON photo_reveals.requester_id = users.id 
        WHERE photo_reveals.requestee_id = ? AND photo_reveals.status = 'pending'
    ''', (user_id,)).fetchall()

    # Get contact share requests sent to the current user
    contact_shares = conn.execute('''
        SELECT contact_shares.requester_id, users.username, users.name, contact_shares.status 
        FROM contact_shares 
        JOIN users ON contact_shares.requester_id = users.id 
        WHERE contact_shares.requestee_id = ? AND contact_shares.status = 'pending'
    ''', (user_id,)).fetchall()

    photo_reveal_notifications = conn.execute('SELECT message, id, "photo" as type FROM photo_reveals WHERE requester_id = ? AND message IS NOT NULL AND message != "Acknowledged" ORDER BY id DESC', (user_id,)).fetchall()
    contact_share_notifications = conn.execute('SELECT message, id, "contact" as type FROM contact_shares WHERE requester_id = ? AND message IS NOT NULL AND message != "Acknowledged" ORDER BY id DESC', (user_id,)).fetchall()
    notifications = photo_reveal_notifications + contact_share_notifications
    notifications.sort(key=lambda x: x['id'], reverse=True)
    conn.close()
    return render_template('notifications.html', notifications=notifications, photo_reveals=photo_reveals, contact_shares=contact_shares)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        
        conn = get_db_connection()
        conn.execute('INSERT INTO contact_messages (name, email, message) VALUES (?, ?, ?)', 
                     (name, email, message))
        conn.commit()
        conn.close()

        return render_template('contact.html', success=True)
    return render_template('contact.html')

@app.route('/ai_suggestions')
def ai_suggestions():
    return render_template('ai_suggestions.html', matches=g.matches, user=g.user)

@app.route('/matches')
def matches():
    return render_template('matches.html', matches=g.matches, user=g.user)

@app.route('/settings')
def settings():
    return render_template('settings.html', user=g.user)

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/admin/contact_messages')
def view_contact_messages():
    conn = get_db_connection()
    messages = conn.execute('SELECT * FROM contact_messages').fetchall()
    conn.close()
    return render_template('admin_contact_messages.html', messages=messages)

@app.route('/delete_data', methods=['POST'])
def delete_data():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()

    try:
        # Delete user's photos
        conn.execute('DELETE FROM photos WHERE user_id = ?', (user_id,))
        
        # Delete user's contact messages
        conn.execute('DELETE FROM contact_messages WHERE email = (SELECT email FROM users WHERE id = ?)', (user_id,))
        
        # Delete user's notifications
        conn.execute('DELETE FROM photo_reveals WHERE requester_id = ? OR requestee_id = ?', (user_id, user_id))
        conn.execute('DELETE FROM contact_shares WHERE requester_id = ? OR requestee_id = ?', (user_id, user_id))
        
        # Delete user's profile
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))

        conn.commit()
        conn.close()

        # Log the user out after deletion
        session.pop('user_id', None)
        return redirect(url_for('login'))
    except Exception as e:
        conn.close()
        return jsonify(status='error', message=str(e)), 500
    
@app.route('/contact_faqs')
def contact_faqs():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('contact_faqs.html')


if __name__ == '__main__':
    app.run(debug=True)

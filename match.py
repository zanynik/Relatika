import sqlite3
from sentence_transformers import SentenceTransformer, util

# Load the model
model = SentenceTransformer('all-MiniLM-L6-v2')

# Connect to the SQLite database
conn = sqlite3.connect('users.db')
cursor = conn.cursor()

# Retrieve all user profiles
cursor.execute("SELECT id, about FROM users")
users = cursor.fetchall()

# Calculate embeddings for all profiles
profiles = [user[1] for user in users]
embeddings = model.encode(profiles)

# Calculate similarity percentages and store them in a new table
cursor.execute('''CREATE TABLE IF NOT EXISTS user_matches (
                  user1_id INTEGER,
                  user2_id INTEGER,
                  cosine_similarity REAL,
                  PRIMARY KEY (user1_id, user2_id))''')

for i in range(len(users)):
    for j in range(len(users)):
        if i != j:
            cosine_sim = util.cos_sim(embeddings[i], embeddings[j]).item()
            cosine_sim_percentage = ((cosine_sim + 1) / 2) * 100

            # Insert the results into the database
            cursor.execute('''INSERT OR REPLACE INTO user_matches (user1_id, user2_id, cosine_similarity)
                              VALUES (?, ?, ?)''',
                           (users[i][0], users[j][0], cosine_sim_percentage))

# Commit the changes and close the connection
conn.commit()
conn.close()

"""
Social Media Scheduler (Standalone Version)

This is a production-ready, standalone version of the Social Media Scheduler.
It features:
    - Unlimited RSS feeds and scheduled posts.
    - A sidebar UI for entering Twitter and Instagram API credentials.
    - Fetching headlines from RSS feeds and auto‐generating post content.
    - Scheduling posts to be published automatically on Twitter and Instagram.
    - A background scheduler (daemon thread) to process scheduled posts.

Requirements:
    pip install -r requirements.txt
"""

import os
import json
import time
import threading
from datetime import datetime

import streamlit as st
import feedparser
import tweepy
from instagrapi import Client

# -------------------- Helper Function for Rerun --------------------
def rerun_app():
    """
    Force the app to rerun.
    Tries st.rerun() first, falls back to st.experimental_rerun() if available, or asks the user to refresh.
    """
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.info("Please refresh the page to see the update.")

# -------------------- CONFIGURATION --------------------
RSS_FEEDS_FILE = "user_rss_feeds.json"
POSTS_FILE = "scheduled_posts.json"

TOP_RSS_FEEDS = {
    "BBC News": "http://feeds.bbci.co.uk/news/rss.xml",
    "CNN": "http://rss.cnn.com/rss/cnn_topstories.rss",
    "ESPN Sports": "https://www.espn.com/espn/rss/news",
    "TechCrunch": "https://techcrunch.com/feed/",
    "Reuters": "http://feeds.reuters.com/reuters/topNews",
    "Bloomberg": "https://www.bloomberg.com/feed",
    "NY Times": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "Google Developers": "https://developers.google.com/web/updates/rss.xml",
    "YouTube": "https://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw",
    "Twitter Blog": "https://blog.twitter.com/api/blog.rss?name=engineering",
    "Wikipedia Featured": "http://en.wikipedia.org/w/api.php?action=featuredfeed&feed=featured",
}

# -------------------- API CREDENTIALS UI --------------------
st.sidebar.header("API Credentials")
twitter_api_key = st.sidebar.text_input("Twitter API Key", value="your_api_key")
twitter_api_secret = st.sidebar.text_input("Twitter API Secret", value="your_api_secret")
twitter_access_token = st.sidebar.text_input("Twitter Access Token", value="your_access_token")
twitter_access_secret = st.sidebar.text_input("Twitter Access Secret", value="your_access_secret")
insta_username = st.sidebar.text_input("Instagram Username", value="your_instagram_username")
insta_password = st.sidebar.text_input("Instagram Password", value="your_instagram_password", type="password")
DEFAULT_INSTAGRAM_IMAGE = st.sidebar.text_input("Default Instagram Image", value="default_instagram.jpg")

# -------------------- INITIAL SETUP --------------------
for file_path, initial_data in [
    (RSS_FEEDS_FILE, {}),
    (POSTS_FILE, []),
]:
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            json.dump(initial_data, f)

# Initialize Twitter API client using credentials from the UI
try:
    auth = tweepy.OAuthHandler(twitter_api_key, twitter_api_secret)
    auth.set_access_token(twitter_access_token, twitter_access_secret)
    twitter_api = tweepy.API(auth)
    st.sidebar.success("Twitter API initialized.")
except Exception as e:
    st.sidebar.error(f"Error initializing Twitter API: {e}")

# -------------------- Simplified Instagram Login --------------------
ig_client = Client()
session_dir = "sessions"
if not os.path.exists(session_dir):
    os.makedirs(session_dir)
session_file = os.path.join(session_dir, f"{insta_username}.json")
try:
    if os.path.exists(session_file):
        ig_client.load_settings(session_file)
        ig_client.login(insta_username, insta_password)
        st.sidebar.success("Instagram API initialized using saved session.")
    else:
        ig_client.login(insta_username, insta_password)
        ig_client.dump_settings(session_file)
        st.sidebar.success("Instagram API initialized and session saved.")
except Exception as e:
    st.sidebar.error(f"Instagram login failed: {e}")

# -------------------- FUNCTION DEFINITIONS --------------------
def fetch_rss_headlines(feed_url, limit=5):
    try:
        feed = feedparser.parse(feed_url)
        headlines = [
            {"title": entry.title, "summary": entry.summary, "link": entry.link}
            for entry in feed.entries[:limit]
        ]
        return headlines
    except Exception as e:
        st.error(f"❌ Failed to fetch RSS feed: {e}")
        return []

def load_user_rss_feeds():
    try:
        with open(RSS_FEEDS_FILE, "r") as file:
            return json.load(file)
    except Exception as e:
        st.error(f"Error loading RSS feeds: {e}")
        return {}

def save_user_rss_feed(username, feed_name, feed_url):
    feeds = load_user_rss_feeds()
    if username not in feeds:
        feeds[username] = {}
    feeds[username][feed_name] = feed_url
    try:
        with open(RSS_FEEDS_FILE, "w") as file:
            json.dump(feeds, file, indent=4)
        return True
    except Exception as e:
        st.error(f"Failed to save RSS feed: {e}")
        return False

def remove_user_rss_feed(username, feed_name):
    feeds = load_user_rss_feeds()
    if username in feeds and feed_name in feeds[username]:
        del feeds[username][feed_name]
        try:
            with open(RSS_FEEDS_FILE, "w") as file:
                json.dump(feeds, file, indent=4)
        except Exception as e:
            st.error(f"Error removing RSS feed: {e}")

def load_scheduled_posts():
    try:
        with open(POSTS_FILE, "r") as file:
            return json.load(file)
    except Exception as e:
        st.error(f"Error loading scheduled posts: {e}")
        return []

def save_scheduled_posts(posts):
    try:
        with open(POSTS_FILE, "w") as file:
            json.dump(posts, file, indent=4)
    except Exception as e:
        st.error(f"Error saving scheduled posts: {e}")

def schedule_social_media_post(username, content, scheduled_time):
    posts = load_scheduled_posts()
    post = {
        "username": username,
        "content": content,
        "scheduled_time": scheduled_time.isoformat(),
        "posted": False,
    }
    posts.append(post)
    save_scheduled_posts(posts)
    return True

def post_to_twitter(content):
    try:
        twitter_api.update_status(content)
        st.info("Posted to Twitter successfully.")
    except Exception as e:
        st.error(f"Twitter posting failed: {e}")

def post_to_instagram(content, image_path=DEFAULT_INSTAGRAM_IMAGE):
    if not os.path.exists(image_path):
        st.error("Default Instagram image not found. Cannot post to Instagram.")
        return
    try:
        ig_client.photo_upload(image_path, content)
        st.info("Posted to Instagram successfully.")
    except Exception as e:
        st.error(f"Instagram posting failed: {e}")

def process_scheduled_posts():
    while True:
        posts = load_scheduled_posts()
        updated = False
        for post in posts:
            if not post.get("posted", False):
                scheduled_time = datetime.fromisoformat(post["scheduled_time"])
                if datetime.now() >= scheduled_time:
                    post_to_twitter(post["content"])
                    post_to_instagram(post["content"])
                    post["posted"] = True
                    updated = True
        if updated:
            save_scheduled_posts(posts)
        time.sleep(60)

if "scheduler_thread_started" not in st.session_state:
    scheduler_thread = threading.Thread(target=process_scheduled_posts, daemon=True)
    scheduler_thread.start()
    st.session_state["scheduler_thread_started"] = True

# -------------------- STREAMLIT USER INTERFACE --------------------
st.title("🚀 Social Media Scheduler")

st.subheader("🔑 Login")
username = st.text_input("Enter your username:", value="local")

if username:
    st.success(f"✅ Logged in as **{username}**")
    
    st.subheader("📢 Manage Your RSS Feeds")
    user_feeds = load_user_rss_feeds().get(username, {})

    if user_feeds:
        st.write("Your Saved Feeds:")
        for name, url in user_feeds.items():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"🔗 **{name}**: [{url}]({url})")
            with col2:
                if st.button("Remove", key=f"remove_{name}"):
                    remove_user_rss_feed(username, name)
                    st.rerun()

    st.write("➕ Save a High-Ranking RSS Feed")
    selected_top_feed = st.selectbox("Choose a Feed to Save", ["Select"] + list(TOP_RSS_FEEDS.keys()))
    if selected_top_feed != "Select" and st.button("Save Selected Feed"):
        if save_user_rss_feed(username, selected_top_feed, TOP_RSS_FEEDS[selected_top_feed]):
            st.success("✅ RSS Feed added successfully!")
            st.rerun()

    st.write("➕ Add a Custom RSS Feed")
    new_feed_name = st.text_input("Feed Name:", key="new_feed_name")
    new_feed_url = st.text_input("Feed URL:", key="new_feed_url")
    if st.button("Save Custom Feed"):
        if new_feed_name and new_feed_url:
            if save_user_rss_feed(username, new_feed_name, new_feed_url):
                st.success("✅ Custom RSS Feed added successfully!")
                st.rerun()
        else:
            st.warning("Please provide both a feed name and URL.")

    st.subheader("📜 Select a Headline from Your Feeds")
    saved_feeds = list(user_feeds.keys()) if user_feeds else []
    selected_feed = st.selectbox("Choose a feed", ["Select"] + saved_feeds, key="selected_feed")
    if selected_feed != "Select" and st.button("Fetch Headlines", key="fetch_headlines"):
        headlines = fetch_rss_headlines(user_feeds[selected_feed])
        if headlines:
            st.session_state["rss_headlines"] = headlines
            st.success(f"✅ Fetched {len(headlines)} headlines from {selected_feed}")
        else:
            st.warning("⚠ No headlines found!")

    if "rss_headlines" in st.session_state and st.session_state["rss_headlines"]:
        selected_headline = st.selectbox(
            "Choose a headline",
            [f"{item['title']} - {item['link']}" for item in st.session_state["rss_headlines"]],
            key="selected_headline",
        )
        if selected_headline:
            title, link = selected_headline.split(" - ", 1)
            post_content = f"📢 {title}\n🔗 {link}"
            st.text_area("Generated Post Content", post_content, height=100, disabled=True)
            st.subheader("⏰ Schedule Your Post")
            scheduled_time_input = st.text_input("Enter scheduled time (YYYY-MM-DD HH:MM):", key="scheduled_time")
            if st.button("Schedule Post", key="schedule_post"):
                try:
                    scheduled_time = datetime.strptime(scheduled_time_input, "%Y-%m-%d %H:%M")
                    if schedule_social_media_post(username, post_content, scheduled_time):
                        st.success("✅ Post scheduled successfully!")
                except ValueError:
                    st.error("Please enter the time in the correct format: YYYY-MM-DD HH:MM")

    st.markdown("### 🚀 What's Next?")
    st.markdown("- Customize API credentials and settings as needed")
    st.markdown("- Enjoy unlimited scheduling and RSS feed management!")
else:
    st.info("Please enter your username to continue.")

"""
Production-Ready Social Media Scheduler with Premium Features,
Unlimited Scheduling, Payment Integration (feature flag), and API Credentials UI

Features:
    - Free users: limited to 3 RSS feeds and 3 scheduled posts.
    - Premium users (upgrade for $9.99/month): unlimited RSS feeds and scheduling.
    - Real Stripe payment integration (can be turned on/off with ENABLE_PAYMENT).
    - Users can enter their Twitter and Instagram API credentials via the sidebar.
    - Fetch headlines from saved feeds and auto‐generate post content.
    - Schedule posts to be automatically published on Twitter and Instagram.
    - A background scheduler (daemon thread) processes scheduled posts.

Note:
    - Replace placeholder values in the Stripe checkout URL as needed.
    - Ensure that the default Instagram image exists in the working directory.
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
import stripe

# -------------------- CONFIGURATION --------------------

# Feature flag: Set to True to enable real payment processing, or False to simulate upgrades for testing.
ENABLE_PAYMENT = True

# File paths for local storage
RSS_FEEDS_FILE = "user_rss_feeds.json"
POSTS_FILE = "scheduled_posts.json"
USER_STATUS_FILE = "user_status.json"

# Free user limits
FREE_RSS_FEED_LIMIT = 3
FREE_SCHEDULED_POST_LIMIT = 3

# Premium pricing details
PREMIUM_PRICE_MONTHLY = 9.99  # $9.99/month

# Predefined high-ranking RSS feeds
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

# Stripe API credentials (replace with your actual Stripe secret key)
stripe.api_key = "your_stripe_secret_key"

# -------------------- API CREDENTIALS UI --------------------
st.sidebar.header("API Credentials")
# Users can enter (or update) their API credentials here.
twitter_api_key = st.sidebar.text_input("Twitter API Key", value="your_api_key")
twitter_api_secret = st.sidebar.text_input("Twitter API Secret", value="your_api_secret")
twitter_access_token = st.sidebar.text_input("Twitter Access Token", value="your_access_token")
twitter_access_secret = st.sidebar.text_input("Twitter Access Secret", value="your_access_secret")
insta_username = st.sidebar.text_input("Instagram Username", value="your_instagram_username")
insta_password = st.sidebar.text_input("Instagram Password", value="your_instagram_password", type="password")
# Path to the default Instagram image (ensure this file exists)
DEFAULT_INSTAGRAM_IMAGE = st.sidebar.text_input("Default Instagram Image", value="default_instagram.jpg")

# -------------------- INITIAL SETUP --------------------

# Ensure storage files exist with appropriate initial data
for file_path, initial_data in [
    (RSS_FEEDS_FILE, {}),
    (POSTS_FILE, []),
    (USER_STATUS_FILE, {}),
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

# Initialize Instagram client using credentials from the UI
ig_client = Client()
try:
    ig_client.login(insta_username, insta_password)
    st.sidebar.success("Instagram API initialized.")
except Exception as e:
    st.sidebar.warning(f"Instagram login failed: {e}")

# -------------------- USER STATUS FUNCTIONS --------------------

def load_user_status():
    try:
        with open(USER_STATUS_FILE, "r") as file:
            return json.load(file)
    except Exception as e:
        st.error(f"Error loading user status: {e}")
        return {}

def save_user_status(status_data):
    try:
        with open(USER_STATUS_FILE, "w") as file:
            json.dump(status_data, file, indent=4)
    except Exception as e:
        st.error(f"Error saving user status: {e}")

def get_user_status(username):
    status_data = load_user_status()
    return status_data.get(username, "free")

def upgrade_user_status(username):
    status_data = load_user_status()
    status_data[username] = "premium"
    save_user_status(status_data)

# -------------------- STRIPE PAYMENT FUNCTIONS --------------------

def create_stripe_checkout_session(username):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Premium Upgrade',
                    },
                    'unit_amount': int(PREMIUM_PRICE_MONTHLY * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"http://localhost:8501/?session_id={{CHECKOUT_SESSION_ID}}&username={username}",
            cancel_url="http://localhost:8501/?cancel=1",
        )
        return session
    except Exception as e:
        st.error(f"Error creating Stripe checkout session: {e}")
        return None

# -------------------- PAYMENT VERIFICATION --------------------
if ENABLE_PAYMENT:
    query_params = st.experimental_get_query_params()
    if "session_id" in query_params and "username" in query_params:
        session_id = query_params["session_id"][0]
        username_param = query_params["username"][0]
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == "paid":
                upgrade_user_status(username_param)
                st.success("🎉 Congratulations! Your account has been upgraded to Premium.")
                st.experimental_set_query_params()
        except Exception as e:
            st.error(f"Error verifying payment: {e}")

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
    if get_user_status(username) == "free" and len(feeds[username]) >= FREE_RSS_FEED_LIMIT:
        st.warning("⚠ Free users can only save 3 RSS feeds. Upgrade for unlimited feeds.")
        return False
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
    if get_user_status(username) == "free":
        user_posts = [p for p in posts if p["username"] == username and not p.get("posted", False)]
        if len(user_posts) >= FREE_SCHEDULED_POST_LIMIT:
            st.warning(f"⚠ Free users can only schedule up to {FREE_SCHEDULED_POST_LIMIT} posts. Upgrade for unlimited scheduling.")
            return False
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

st.title("🚀 Social Media Scheduler with Premium Features")

st.subheader("🔑 Login")
username = st.text_input("Enter your username:")

if username:
    account_status = get_user_status(username)
    st.success(f"✅ Logged in as **{username}** | **Account Type:** {account_status.capitalize()}")

    if account_status == "free":
        st.subheader("💰 Upgrade to Premium")
        st.markdown(f"Unlock unlimited RSS feeds and scheduled posts for **${PREMIUM_PRICE_MONTHLY}/month**.")
        if st.button("Upgrade Now"):
            if ENABLE_PAYMENT:
                session = create_stripe_checkout_session(username)
                if session:
                    st.markdown(f"Please [click here to pay]({session.url}) to complete your upgrade.")
            else:
                upgrade_user_status(username)
                st.success("🎉 Simulated upgrade complete. Your account is now Premium!")
                st.experimental_rerun()
    else:
        st.info("⭐ You are a Premium user with unlimited features.")

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
                    st.experimental_rerun()

    st.write("➕ Save a High-Ranking RSS Feed")
    selected_top_feed = st.selectbox("Choose a Feed to Save", ["Select"] + list(TOP_RSS_FEEDS.keys()))
    if selected_top_feed != "Select" and st.button("Save Selected Feed"):
        if save_user_rss_feed(username, selected_top_feed, TOP_RSS_FEEDS[selected_top_feed]):
            st.success("✅ RSS Feed added successfully!")
            st.experimental_rerun()

    if get_user_status(username) == "premium" or len(user_feeds) < FREE_RSS_FEED_LIMIT:
        st.write("➕ Add a Custom RSS Feed")
        new_feed_name = st.text_input("Feed Name:", key="new_feed_name")
        new_feed_url = st.text_input("Feed URL:", key="new_feed_url")
        if st.button("Save Custom Feed"):
            if new_feed_name and new_feed_url:
                if save_user_rss_feed(username, new_feed_name, new_feed_url):
                    st.success("✅ Custom RSS Feed added successfully!")
                    st.experimental_rerun()
            else:
                st.warning("Please provide both a feed name and URL.")
    else:
        st.warning("⚠ Free users can only save 3 RSS feeds. Upgrade for unlimited feeds!")

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
    st.markdown("- Package as a .zip for download")
    st.markdown("- Further integrate with Stripe for recurring billing and webhooks")
    st.markdown("- Build a dedicated landing page to drive sales")
    st.markdown("Would you like a ready-to-sell version now?")
else:
    st.info("Please enter your username to continue.")

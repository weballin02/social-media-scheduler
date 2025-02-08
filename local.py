"""
Local Social Media Content Generator with Monetization and Test-Card Payment Simulation

Features:
  • Local user registration and login (using JSON files)
  • Local storage of user metrics (RSS headlines fetched, Instagram posts scheduled, scheduled posts)
  • RSS feed functionality with image downloading (using feedparser, BeautifulSoup, requests, and Pillow)
  • Instagram posting via instagrapi with session saving (to avoid repeated 2FA)
  • Twitter posting via tweepy (placeholder functions for actual posting)
  • Post scheduling via APScheduler
  • A dashboard and separate pages for RSS feeds, Instagram scheduling, and account upgrade
  • Stripe Checkout integration for monetization with two pricing tiers:
         - Premium: $9.99/month (unlimited features)
         - Pro: $19.99/month (priority support, etc.)
  • Global TEST_MODE flag: When True, all external calls are simulated.
  • ALLOW_TEST_CARD flag: When True (even in production), the Stripe Checkout session is simulated using test card data.
  • Uses st.query_params (the new API) instead of the deprecated experimental_* methods.
  
Note: Replace placeholder API keys (like the Stripe secret key) with your actual production keys.
"""

import os
import json
import time
import logging
import atexit
from datetime import datetime

import streamlit as st
import feedparser
import requests
import tweepy  # (Assume you have actual Twitter posting functions elsewhere)
from instagrapi import Client
from PIL import Image
from io import BytesIO
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
import pytz
import stripe

# ----------------------------- Global Configuration -----------------------------
# Set these as needed:
TEST_MODE = False            # When True, simulate all external calls.
ALLOW_TEST_CARD = True       # When True (even if TEST_MODE is False), simulate Stripe Checkout using test card data.

# Pricing tiers (psychologically optimized)
PRICING_TIERS = {
    "Premium": 9.99,
    "Pro": 19.99
}

# Replace with your actual live Stripe secret key
stripe.api_key = "your_live_stripe_secret_key"

# Local storage files
USERS_FILE = "users.json"
USER_METRICS_FILE = "user_metrics.json"

# ----------------------------- Logging Configuration -----------------------------
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ----------------------------- Helper Functions -----------------------------
def rerun_app():
    """Force the app to rerun."""
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.info("Please refresh the page to see updates.")

# ----------------------------- User Management -----------------------------
def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading users: {e}")
    return {}

def save_users(users):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=4)
    except Exception as e:
        st.error(f"Error saving users: {e}")

def register_user_local(email, password):
    users = load_users()
    if email in users:
        st.error("User already exists. Please log in.")
        return False
    users[email] = {"password": password, "role": "free"}
    save_users(users)
    initialize_user_metrics(email)
    st.success("Registration successful! Please log in.")
    logger.info(f"User registered: {email}")
    return True

def login_user_local(email, password):
    users = load_users()
    if email not in users:
        st.error("User not found. Please register.")
        return False
    if users[email]["password"] != password:
        st.error("Incorrect password.")
        return False
    st.session_state.user_email = email
    st.session_state.user_role = users[email].get("role", "free")
    st.session_state.logged_in = True
    initialize_user_metrics(email)
    st.success(f"Logged in as {st.session_state.user_role} user!")
    logger.info(f"User logged in: {email}")
    load_and_schedule_existing_posts(email)
    return True

def upgrade_user_plan(username, plan):
    users = load_users()
    if username in users:
        users[username]["role"] = plan
        save_users(users)
        st.session_state.user_role = plan
        logger.info(f"User {username} upgraded to {plan}")
    else:
        st.error("User not found during upgrade.")

# ----------------------------- User Metrics Management -----------------------------
def load_user_metrics():
    if os.path.exists(USER_METRICS_FILE):
        try:
            with open(USER_METRICS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading user metrics: {e}")
    return {}

def save_user_metrics(metrics):
    try:
        with open(USER_METRICS_FILE, "w") as f:
            json.dump(metrics, f, indent=4)
    except Exception as e:
        st.error(f"Error saving user metrics: {e}")

def initialize_user_metrics(email):
    metrics = load_user_metrics()
    if email not in metrics:
        metrics[email] = {
            "rss_headlines_fetched": 0,
            "instagram_posts_scheduled": 0,
            "scheduled_posts": []
        }
        save_user_metrics(metrics)
        logger.info(f"Initialized metrics for user: {email}")

def get_user_metrics(email):
    metrics = load_user_metrics()
    return metrics.get(email, {"rss_headlines_fetched": 0, "instagram_posts_scheduled": 0, "scheduled_posts": []})

def update_user_metric(email, metric, value):
    metrics = load_user_metrics()
    if email not in metrics:
        initialize_user_metrics(email)
        metrics = load_user_metrics()
    metrics[email][metric] = metrics[email].get(metric, 0) + value
    save_user_metrics(metrics)
    logger.info(f"Updated {metric} by {value} for user {email}")

def add_scheduled_post(email, post_data):
    metrics = load_user_metrics()
    if email not in metrics:
        initialize_user_metrics(email)
        metrics = load_user_metrics()
    scheduled_posts = metrics[email].get("scheduled_posts", [])
    scheduled_posts.append(post_data)
    metrics[email]["scheduled_posts"] = scheduled_posts
    save_user_metrics(metrics)
    logger.info(f"Added scheduled post for user {email}: {post_data}")

def remove_scheduled_post(email, post_id):
    metrics = load_user_metrics()
    if email in metrics:
        scheduled_posts = metrics[email].get("scheduled_posts", [])
        updated_posts = [post for post in scheduled_posts if post['id'] != post_id]
        metrics[email]["scheduled_posts"] = updated_posts
        save_user_metrics(metrics)
        logger.info(f"Removed scheduled post {post_id} for user {email}")

def update_scheduled_post(email, post_id, updated_data):
    metrics = load_user_metrics()
    if email in metrics:
        scheduled_posts = metrics[email].get("scheduled_posts", [])
        for idx, post in enumerate(scheduled_posts):
            if post['id'] == post_id:
                scheduled_posts[idx].update(updated_data)
                break
        metrics[email]["scheduled_posts"] = scheduled_posts
        save_user_metrics(metrics)
        logger.info(f"Updated scheduled post {post_id} for user {email}: {updated_data}")

# ----------------------------- Stripe Checkout Integration -----------------------------
def create_stripe_checkout_session(username, plan):
    # If in test mode or if test card simulation is enabled, simulate the session.
    if TEST_MODE or ALLOW_TEST_CARD:
        logger.info("Simulated Stripe session created (using test card simulation).")
        class DummySession:
            payment_status = "paid"
            url = "https://example.com/simulated-checkout"
        return DummySession()
    try:
        unit_amount = int(PRICING_TIERS[plan] * 100)
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': f'{plan} Upgrade'},
                    'unit_amount': unit_amount,
                },
                'quantity': 1,
            }],
            mode='payment',
            # Make sure these URLs point to your deployed app!
            success_url=f"http://your-app-url/?session_id={{CHECKOUT_SESSION_ID}}&username={username}&plan={plan}",
            cancel_url="http://your-app-url/?cancel=1",
        )
        return session
    except Exception as e:
        st.error(f"Error creating Stripe session: {e}")
        return None

# ----------------------------- APScheduler Initialization -----------------------------
@st.cache_resource(show_spinner=False)
def init_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("APScheduler started.")
    return scheduler

scheduler = init_scheduler()
atexit.register(lambda: scheduler.shutdown())

def add_job(email, post_id, image_path, caption, scheduled_time):
    try:
        scheduler.add_job(
            schedule_instagram_post,
            'date',
            run_date=scheduled_time,
            args=[email, post_id, image_path, caption, scheduled_time],
            id=post_id,
            replace_existing=True
        )
        logger.info(f"Job {post_id} scheduled at {scheduled_time} for {email}")
    except Exception as e:
        logger.error(f"Failed to schedule job {post_id}: {e}")
        st.error(f"Failed to schedule post: {e}")

def load_and_schedule_existing_posts(email):
    metrics = get_user_metrics(email)
    scheduled_posts = metrics.get("scheduled_posts", [])
    for post in scheduled_posts:
        post_id = post['id']
        image_path = post['image_path']
        caption = post['caption']
        scheduled_time = datetime.fromisoformat(post['scheduled_time'])
        timezone = post['timezone']
        scheduled_time = pytz.timezone(timezone).localize(scheduled_time)
        if not scheduler.get_job(post_id):
            if scheduled_time > datetime.now(pytz.timezone(timezone)):
                add_job(email, post_id, image_path, caption, scheduled_time)
                logger.info(f"Loaded and scheduled post {post_id} for {email}")
            else:
                logger.info(f"Post {post_id} scheduled time passed. Uploading immediately.")
                schedule_instagram_post(email, post_id, image_path, caption, datetime.now(pytz.timezone(timezone)))

# ----------------------------- Placeholder Functions for Social Media Posting -----------------------------
def post_to_twitter(caption):
    # Placeholder: Integrate with tweepy and your Twitter credentials.
    logger.info(f"Posting to Twitter: {caption}")

def post_to_instagram(caption, image_path):
    # Placeholder: Integrate with instagrapi and your Instagram credentials.
    logger.info(f"Posting to Instagram: {caption} with image {image_path}")

def schedule_instagram_post(email, post_id, image_path, caption, scheduled_time):
    if TEST_MODE:
        st.info("Simulated Instagram post upload.")
        logger.info(f"Simulated upload for post {post_id} for user {email}.")
        return
    try:
        client = Client()
        session_dir = "sessions"
        if not os.path.exists(session_dir):
            os.makedirs(session_dir)
        # Assume the user’s Instagram credentials are stored and used here.
        # (Replace with your actual logic to load a session.)
        session_file = os.path.join(session_dir, f"{email}_instagram.json")
        if os.path.exists(session_file):
            client.load_settings(session_file)
            # For simplicity, we assume login here.
            logger.info(f"Loaded Instagram session for {email}")
        else:
            st.error(f"Instagram session file not found for {email}. Please re-login.")
            return
        client.photo_upload(image_path, caption)
        logger.info(f"Scheduled Instagram post {post_id} uploaded.")
        update_user_metric(email, "instagram_posts_scheduled", 1)
        remove_scheduled_post(email, post_id)
    except Exception as e:
        logger.error(f"Failed to upload scheduled Instagram post {post_id}: {e}")

# ----------------------------- Social Media Scheduler Pages -----------------------------
def render_instagram_scheduler_page():
    st.header("📅 Instagram Scheduler")
    st.subheader("Plan and Automate Your Instagram Content")
    insta_username = st.text_input("Instagram Username")
    insta_password = st.text_input("Instagram Password", type="password")
    image_directory = st.text_input("Image Directory", "generated_posts")
    timezone = st.selectbox("Select Timezone", pytz.all_timezones, index=pytz.all_timezones.index('UTC'))
    if st.button("Login to Instagram"):
        if not insta_username or not insta_password:
            st.error("Please provide Instagram credentials!")
            logger.warning("Instagram login attempted without credentials.")
        else:
            try:
                client = Client()
                client.login(insta_username, insta_password)
                st.session_state.instagram_client = client
                if not os.path.exists("sessions"):
                    os.makedirs("sessions")
                session_file = f"sessions/{insta_username}.json"
                client.dump_settings(session_file)
                st.success("Logged into Instagram and session saved!")
                logger.info(f"User {insta_username} logged into Instagram; session saved.")
            except Exception as e:
                st.error(f"Login failed: {e}")
                logger.error(f"Instagram login failed for {insta_username}: {e}")
    st.markdown("---")
    st.subheader("Schedule New Instagram Posts")
    if st.session_state.user_email:
        metrics = get_user_metrics(st.session_state.user_email)
        scheduled_posts = metrics.get("scheduled_posts", [])
    else:
        scheduled_posts = []
    fetched_headlines = st.session_state.rss_headlines
    scheduled_captions = [post.get('caption', '').replace(f" Read more at: {post.get('article_url', '')}", '') for post in scheduled_posts]
    unscheduled_headlines = [h for h in fetched_headlines if h['title'] not in scheduled_captions]
    if not unscheduled_headlines:
        st.info("No unscheduled posts available. Fetch more headlines or schedule existing posts.")
        return
    title_to_headline = {h['title']: h for h in unscheduled_headlines}
    selected_titles = st.multiselect("Select Post(s) to Schedule", options=list(title_to_headline.keys()))
    if selected_titles:
        for title in selected_titles:
            headline = title_to_headline[title]
            st.markdown(f"### {headline['title']}")
            if headline['image_path'] and os.path.exists(headline['image_path']):
                st.image(headline['image_path'], caption="Fetched Image", use_container_width=True)
            else:
                st.warning("No image available for this headline.")
            with st.form(key=f"schedule_form_{title}", clear_on_submit=False):
                col1, col2 = st.columns(2)
                with col1:
                    scheduled_date = st.date_input(f"Select Date for '{title}'", datetime.now(), key=f"date_{title}")
                with col2:
                    scheduled_time = st.time_input(f"Select Time for '{title}'", datetime.now().time(), key=f"time_{title}")
                caption = st.text_area(f"Post Caption for '{title}'", headline['title'], key=f"caption_{title}")
                submitted = st.form_submit_button(f"Schedule '{title}'")
                if submitted:
                    if not st.session_state.instagram_client:
                        st.error("Please login to Instagram first.")
                        logger.warning("Attempted scheduling without Instagram login.")
                    else:
                        try:
                            scheduled_datetime = datetime.combine(scheduled_date, scheduled_time)
                            scheduled_datetime = pytz.timezone(timezone).localize(scheduled_datetime)
                        except Exception as e:
                            st.error(f"Error in scheduling datetime: {e}")
                            logger.error(f"Error scheduling post '{title}': {e}")
                            continue
                        now = datetime.now(pytz.timezone(timezone))
                        if scheduled_datetime <= now:
                            st.error("Scheduled time must be in the future!")
                            logger.warning(f"User attempted to schedule '{title}' in the past.")
                            continue
                        post_id = f"{st.session_state.user_email}_{int(time.time())}_{title.replace(' ', '_')}"
                        full_caption = f"{caption}\nRead more at: {headline['link']}" if headline['link'] else caption
                        post_data = {
                            "id": post_id,
                            "image_path": headline['image_path'],
                            "caption": full_caption,
                            "scheduled_time": scheduled_datetime.isoformat(),
                            "timezone": timezone,
                            "article_url": headline['link'] if headline['link'] else ""
                        }
                        add_scheduled_post(st.session_state.user_email, post_data)
                        add_job(st.session_state.user_email, post_id, headline['image_path'], full_caption, scheduled_datetime)
                        st.success(f"Post '{title}' scheduled for {scheduled_datetime.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        logger.info(f"Scheduled post {post_id} for {st.session_state.user_email}")
    st.markdown("---")
    st.subheader("Your Scheduled Posts")
    if scheduled_posts:
        for post in scheduled_posts:
            with st.expander(f"Post ID: {post['id']}"):
                col1, col2 = st.columns([1, 2])
                with col1:
                    if post['image_path'] and os.path.exists(post['image_path']):
                        st.image(post['image_path'], use_container_width=True)
                    else:
                        st.warning("Image not available.")
                with col2:
                    st.markdown(f"**Caption:** {post['caption']}")
                    scheduled_time = datetime.fromisoformat(post['scheduled_time'])
                    st.markdown(f"**Scheduled Time:** {scheduled_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    if post.get('article_url'):
                        st.markdown(f"**Article URL:** [Read more]({post['article_url']})")
                    else:
                        st.markdown("**Article URL:** Not available")
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        if st.button(f"Edit {post['id']}", key=f"edit_{post['id']}"):
                            edit_scheduled_post(st.session_state.user_email, post)
                    with col_b:
                        if st.button(f"Delete {post['id']}", key=f"delete_{post['id']}"):
                            delete_scheduled_post(st.session_state.user_email, post['id'])
                    with col_c:
                        if st.button(f"Send Now {post['id']}", key=f"send_{post['id']}"):
                            send_post_now(st.session_state.user_email, post['id'])
    else:
        st.info("No scheduled posts found.")

def render_upgrade_page():
    st.header("💰 Upgrade Your Account")
    st.markdown("Unlock unlimited RSS feeds and scheduling by upgrading your account.")
    st.markdown("- **Premium:** $9.99/month (Unlimited features)")
    st.markdown("- **Pro:** $19.99/month (Unlimited features with priority support)")
    selected_plan = st.selectbox("Select your plan", list(PRICING_TIERS.keys()))
    if st.button("Upgrade Now"):
        session = create_stripe_checkout_session(st.session_state.user_email, selected_plan)
        if session:
            st.markdown(f"Please [click here to pay]({session.url}) to complete your upgrade.")

def render_dashboard():
    metrics = get_user_metrics(st.session_state.user_email)
    thresholds = {"rss_headlines_fetched": 10, "instagram_posts_scheduled": 5}
    st.header("📊 Dashboard")
    st.subheader("Your Activity Overview")
    col1, col2 = st.columns(2)
    def render_metric_card(column, label, current, total, icon_url, progress_color):
        with column:
            st.markdown(
                f"""
                <div style="text-align: center; border: 1px solid #e6e6e6; padding: 15px; border-radius: 10px;">
                    <img src="{icon_url}" alt="{label}" style="width: 50px; height: 50px; margin-bottom: 10px;" />
                    <h3 style="margin: 5px 0;">{label}</h3>
                    <p style="margin: 5px 0; font-size: 18px;">{current} / {total}</p>
                    <div style="height: 20px; background-color: #f3f3f3; border-radius: 10px;">
                        <div style="width: {min(current / total * 100, 100)}%; background-color: {progress_color}; height: 100%; border-radius: 10px;"></div>
                    </div>
                    <p style="margin: 5px 0; font-size: 14px; color: gray;">{int(current / total * 100)}% Completed</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    render_metric_card(
        col1,
        "RSS Headlines Fetched",
        metrics.get("rss_headlines_fetched", 0),
        thresholds.get("rss_headlines_fetched", 10),
        "https://img.icons8.com/color/64/000000/rss.png",
        "#4CAF50" if metrics.get("rss_headlines_fetched", 0) < thresholds.get("rss_headlines_fetched", 10) else "#FF5722",
    )
    render_metric_card(
        col2,
        "Instagram Posts Scheduled",
        metrics.get("instagram_posts_scheduled", 0),
        thresholds.get("instagram_posts_scheduled", 5),
        "https://img.icons8.com/color/64/000000/instagram-new.png",
        "#4CAF50" if metrics.get("instagram_posts_scheduled", 0) < thresholds.get("instagram_posts_scheduled", 5) else "#FF5722",
    )
    if st.session_state.user_role == "free":
        if metrics.get("rss_headlines_fetched", 0) >= thresholds.get("rss_headlines_fetched", 10):
            st.warning("Upgrade to Premium to fetch more RSS headlines!")
        if metrics.get("instagram_posts_scheduled", 0) >= thresholds.get("instagram_posts_scheduled", 5):
            st.warning("Upgrade to Premium to schedule more Instagram posts!")

# ----------------------------- Main App Rendering -----------------------------
def render_user_interface():
    menu = st.sidebar.radio("Navigation", ["Dashboard", "RSS Feeds", "Instagram Scheduler", "Upgrade"])
    if menu == "Dashboard":
        render_dashboard()
    elif menu == "RSS Feeds":
        render_rss_feeds_page()
    elif menu == "Instagram Scheduler":
        render_instagram_scheduler_page()
    elif menu == "Upgrade":
        render_upgrade_page()

def register_user():
    st.header("Register")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    confirm_password = st.text_input("Confirm Password", type="password")
    if st.button("Register"):
        if not email or not password or not confirm_password:
            st.error("Please fill out all fields!")
            logger.warning("Registration attempted with missing fields.")
        elif password != confirm_password:
            st.error("Passwords do not match!")
            logger.warning(f"Registration failed: passwords do not match for {email}.")
        elif len(password) < 6:
            st.error("Password must be at least 6 characters long.")
            logger.warning(f"Registration failed: password too short for {email}.")
        else:
            register_user_local(email, password)

def login_user():
    st.header("Login")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if not email or not password:
            st.error("Please provide both email and password!")
            logger.warning("Login attempted with missing email or password.")
        else:
            if login_user_local(email, password):
                rerun_app()

def main():
    st.title("🚀 Social Media Content Generator")
    if not st.session_state.get("logged_in", False):
        st.sidebar.title("Authentication")
        auth_mode = st.sidebar.radio("Choose an option:", ["Login", "Register"])
        if auth_mode == "Register":
            register_user()
        elif auth_mode == "Login":
            login_user()
    else:
        render_user_interface()

if __name__ == "__main__":
    main()

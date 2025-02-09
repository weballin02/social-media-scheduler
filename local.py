"""
Local Social Media Content Generator with Monetization and Test-Card Payment Simulation

Features:
  • Local user registration and login (using JSON files)
  • Local storage of user metrics (RSS headlines fetched, Instagram posts scheduled, scheduled posts)
  • RSS feed functionality with image downloading (using feedparser, BeautifulSoup, requests, and Pillow)
  • Instagram posting via instagrapi (with a global client to avoid token issues)
  • Twitter posting via tweepy
  • Post scheduling via APScheduler (jobs run in background threads)
  • A dashboard and separate pages for RSS feeds, Instagram scheduling, and account upgrade
  • Stripe Checkout integration for monetization with two pricing tiers:
         - Premium: $9.99/month
         - Pro: $19.99/month
  • Global TEST_MODE flag: When True, all external calls are simulated.
  • ALLOW_TEST_CARD flag: When True (even in production), Stripe Checkout is simulated.
  • Uses st.query_params (the new API) for reading URL parameters.
  
Before deployment, replace placeholder API keys/credentials and URLs with your actual production values.
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
import tweepy
from instagrapi import Client
from PIL import Image
from io import BytesIO
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
import pytz
import stripe

# ----------------------------- Global Configuration -----------------------------
# Simulation flags
TEST_MODE = False            # When True, simulate external calls.
ALLOW_TEST_CARD = True       # When True (even if TEST_MODE is False), simulate Stripe Checkout.

# Pricing tiers
PRICING_TIERS = {
    "Premium": 9.99,
    "Pro": 19.99
}

# Replace with your actual API keys
stripe.api_key = "your_live_stripe_secret_key"

# Twitter API credentials (replace with your actual credentials)
TWITTER_API_KEY = "your_twitter_api_key"
TWITTER_API_SECRET = "your_twitter_api_secret"
TWITTER_ACCESS_TOKEN = "your_twitter_access_token"
TWITTER_ACCESS_SECRET = "your_twitter_access_secret"

# Local storage file paths
USERS_FILE = "users.json"
USER_METRICS_FILE = "user_metrics.json"

# ----------------------------- Global Instagram Client -----------------------------
# We use a global variable to hold the Instagram client for background jobs.
global_instagram_client = None

# ----------------------------- Session State Initialization -----------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_role" not in st.session_state:
    st.session_state.user_role = None
if "rss_headlines" not in st.session_state:
    st.session_state.rss_headlines = []
if "scheduled_posts" not in st.session_state:
    st.session_state.scheduled_posts = []

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
            # Replace these URLs with your deployed app URL.
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

# ----------------------------- Social Media Posting Functions -----------------------------
def post_to_twitter(caption):
    try:
        auth = tweepy.OAuthHandler(TWITTER_API_KEY, TWITTER_API_SECRET)
        auth.set_access_token(TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
        api = tweepy.API(auth)
        api.update_status(caption)
        logger.info(f"Tweet posted: {caption}")
    except Exception as e:
        logger.error(f"Error posting to Twitter: {e}")
        raise

def post_to_instagram(caption, image_path):
    global global_instagram_client
    if not global_instagram_client:
        raise Exception("Global Instagram client not found. Please login again.")
    try:
        global_instagram_client.photo_upload(image_path, caption)
        logger.info(f"Instagram post uploaded: {caption} with image {image_path}")
    except Exception as e:
        logger.error(f"Error posting to Instagram: {e}")
        raise

def schedule_instagram_post(email, post_id, image_path, caption, scheduled_time):
    if TEST_MODE:
        st.info("Simulated Instagram post upload.")
        logger.info(f"Simulated upload for post {post_id} for user {email}.")
        return
    try:
        global global_instagram_client
        if not global_instagram_client:
            st.error("Instagram client not found. Please login again.")
            return
        try:
            global_instagram_client.photo_upload(image_path, caption)
        except Exception as e:
            logger.error(f"Initial Instagram post failed for {post_id}: {e}")
            # Attempt to refresh token and retry
            global_instagram_client.relogin()
            global_instagram_client.photo_upload(image_path, caption)
        logger.info(f"Scheduled Instagram post {post_id} uploaded.")
        update_user_metric(email, "instagram_posts_scheduled", 1)
        remove_scheduled_post(email, post_id)
    except Exception as e:
        logger.error(f"Failed to upload scheduled Instagram post {post_id}: {e}")
        st.error(f"Error uploading Instagram post: {e}")

# ----------------------------- RSS Feed Functions -----------------------------
def fetch_headlines(rss_url, limit=5, image_dir="generated_posts"):
    try:
        feed = feedparser.parse(rss_url)
        headlines = []
        for entry in feed.entries[:limit]:
            title = entry.title
            summary = entry.summary if 'summary' in entry else "No summary available."
            link = entry.link
            image_url = None
            if 'media_content' in entry:
                media = entry.media_content
                if isinstance(media, list) and len(media) > 0:
                    image_url = media[0].get('url')
                    logger.info(f"Found media_content image for {title}")
            if not image_url and 'media_thumbnail' in entry:
                media_thumbnails = entry.media_thumbnail
                if isinstance(media_thumbnails, list) and len(media_thumbnails) > 0:
                    image_url = media_thumbnails[0].get('url')
                    logger.info(f"Found media_thumbnail image for {title}")
            if not image_url and 'enclosures' in entry:
                for enclosure in entry.enclosures:
                    if enclosure.get('type', '').startswith('image/'):
                        image_url = enclosure.get('url')
                        logger.info(f"Found enclosure image for {title}")
                        break
            if not image_url and 'summary' in entry:
                soup = BeautifulSoup(entry.summary, 'html.parser')
                img_tag = soup.find('img')
                if img_tag and img_tag.get('src'):
                    image_url = img_tag.get('src')
                    logger.info(f"Found embedded image in summary for {title}")
            image_path = None
            if image_url:
                image_path = download_image(image_url, image_dir=image_dir)
                if image_path:
                    logger.info(f"Downloaded image for {title} to {image_path}")
                else:
                    logger.warning(f"Image download failed for {title}")
            else:
                logger.warning(f"No image found for {title}")
            headlines.append({
                "title": title,
                "summary": summary,
                "link": link,
                "image_url": image_url,
                "image_path": image_path
            })
        logger.info(f"Fetched {len(headlines)} headlines from {rss_url}")
        return headlines
    except Exception as e:
        logger.error(f"Failed to fetch RSS feed from {rss_url}: {e}")
        st.error(f"Failed to fetch RSS feed: {e}")
        return []

def download_image(image_url, image_dir="generated_posts"):
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content)).convert("RGB")
        if not os.path.exists(image_dir):
            os.makedirs(image_dir)
            logger.info(f"Created directory {image_dir}")
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
        image_filename = f"ig_post_{timestamp}.jpg"
        image_path = os.path.join(image_dir, image_filename)
        img.save(image_path)
        logger.info(f"Image saved at {image_path}")
        return image_path
    except Exception as e:
        logger.error(f"Failed to download image from {image_url}: {e}")
        st.error(f"Failed to download image: {e}")
        return None

# ----------------------------- UI Rendering Functions -----------------------------
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
                # Set the global client variable for background jobs
                global global_instagram_client
                global_instagram_client = client
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
                    if not global_instagram_client:
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

def edit_scheduled_post(email, post):
    with st.form(f"edit_form_{post['id']}"):
        st.header(f"Edit Scheduled Post {post['id']}")
        original_caption = post['caption']
        article_url = post.get('article_url', '')
        if article_url:
            original_caption = original_caption.replace(f"\nRead more at: {article_url}", '')
        new_caption = st.text_area("Post Caption", original_caption, key=f"edit_caption_{post['id']}")
        scheduled_time = datetime.fromisoformat(post['scheduled_time'])
        timezone = post.get('timezone', 'UTC')
        col1, col2 = st.columns(2)
        with col1:
            new_date = st.date_input("Select Date", scheduled_time.date(), key=f"edit_date_{post['id']}")
        with col2:
            new_time = st.time_input("Select Time", scheduled_time.time(), key=f"edit_time_{post['id']}")
        new_timezone = st.selectbox("Select Timezone", pytz.all_timezones, index=pytz.all_timezones.index(timezone), key=f"edit_timezone_{post['id']}")
        submitted = st.form_submit_button("Update Post")
        if submitted:
            try:
                new_scheduled_datetime = datetime.combine(new_date, new_time)
                new_scheduled_datetime = pytz.timezone(new_timezone).localize(new_scheduled_datetime)
            except Exception as e:
                st.error(f"Error in scheduling datetime: {e}")
                logger.error(f"Error updating post '{post['id']}': {e}")
                return
            now = datetime.now(pytz.timezone(new_timezone))
            if new_scheduled_datetime <= now:
                st.error("Scheduled time must be in the future!")
                logger.warning(f"User attempted to update post '{post['id']}' to a past time.")
                return
            updated_caption = f"{new_caption}\nRead more at: {post['article_url']}" if post.get('article_url') else new_caption
            updated_data = {
                "caption": updated_caption,
                "scheduled_time": new_scheduled_datetime.isoformat(),
                "timezone": new_timezone
            }
            update_scheduled_post(email, post['id'], updated_data)
            try:
                scheduler.remove_job(post['id'])
                logger.info(f"Removed job {post['id']} for rescheduling.")
            except JobLookupError:
                logger.warning(f"Job {post['id']} not found for removal.")
            add_job(email, post['id'], post['image_path'], updated_caption, new_scheduled_datetime)
            st.success("Scheduled post updated successfully!")
            logger.info(f"Post {post['id']} updated for user {email}.")

def delete_scheduled_post(email, post_id):
    try:
        scheduler.remove_job(post_id)
        logger.info(f"Removed job {post_id} from scheduler.")
    except JobLookupError:
        logger.warning(f"Job {post_id} not found for removal.")
    remove_scheduled_post(email, post_id)
    st.success(f"Scheduled post {post_id} deleted successfully.")
    logger.info(f"Post {post_id} deleted for user {email}.")

def send_post_now(email, post_id):
    """Immediately send the scheduled post identified by post_id."""
    metrics = get_user_metrics(email)
    scheduled_posts = metrics.get("scheduled_posts", [])
    post = next((p for p in scheduled_posts if p['id'] == post_id), None)
    if post is None:
        st.error("Post not found.")
        return
    if post.get("posted", False):
        st.warning("Post already sent.")
        return
    if TEST_MODE:
        st.info("Simulated immediate sending of scheduled post.")
        logger.info(f"Simulated sending post {post_id} immediately for user {email}.")
        update_user_metric(email, "instagram_posts_scheduled", 1)
        remove_scheduled_post(email, post_id)
        return
    try:
        post_to_twitter(post["caption"])
        post_to_instagram(post["caption"], image_path=post["image_path"])
        st.success("Post sent immediately!")
        logger.info(f"Sent post {post_id} immediately for user {email}.")
        update_user_metric(email, "instagram_posts_scheduled", 1)
        remove_scheduled_post(email, post_id)
    except Exception as e:
        st.error(f"Error sending post immediately: {e}")
        logger.error(f"Error sending post {post_id} immediately for user {email}: {e}")

def render_rss_feeds_page():
    st.header("📰 RSS Feeds")
    st.subheader("Explore the Latest News and Create Instagram Posts")
    rss_feeds = {
        "BBC News": "http://feeds.bbci.co.uk/news/rss.xml",
        "CNN": "http://rss.cnn.com/rss/cnn_topstories.rss",
        "Reuters": "http://feeds.reuters.com/reuters/topNews",
    }
    feed_name = st.selectbox("Choose a Feed", list(rss_feeds.keys()))
    rss_url = rss_feeds[feed_name]
    custom_rss_url = st.text_input("Custom RSS Feed URL (optional)", "")
    if custom_rss_url:
        rss_url = custom_rss_url
    num_headlines = st.slider("Number of Headlines", 1, 10, 5)
    if st.button("Fetch Headlines"):
        st.subheader(f"Top {num_headlines} Headlines from {feed_name}")
        st.session_state.rss_headlines = []
        headlines = fetch_headlines(rss_url, limit=num_headlines)
        if headlines:
            progress_bar = st.progress(0)
            total_headlines = len(headlines)
            for idx, entry in enumerate(headlines):
                st.markdown(f"### [{entry['title']}]({entry['link']})")
                st.write(entry['summary'])
                if entry['image_path']:
                    st.image(entry['image_path'], caption="Fetched Image", use_container_width=True)
                    st.session_state.rss_headlines.append(entry)
                else:
                    st.warning("No image available for this headline.")
                update_user_metric(st.session_state.user_email, "rss_headlines_fetched", 1)
                progress_bar.progress((idx + 1) / total_headlines)
                time.sleep(0.5)
            progress_bar.empty()
            st.success("RSS headlines fetched successfully!")
        else:
            st.warning("No headlines found. Try another feed.")
    if st.session_state.rss_headlines:
        st.markdown("## 📸 Generated Instagram Posts from Headlines")
        for idx, post in enumerate(st.session_state.rss_headlines, 1):
            st.markdown(f"### Post {idx}")
            if post.get('image_path') and os.path.exists(post['image_path']):
                st.image(post['image_path'], caption=post['title'], use_container_width=True)
                if st.button(f"Schedule Post {idx}", key=f"schedule_{idx}"):
                    if "instagram_client" not in st.session_state or not global_instagram_client:
                        st.error("Please login to Instagram first.")
                        logger.warning("Attempted scheduling without Instagram login.")
                    else:
                        st.success("Please use the 'Instagram Scheduler' page to schedule this post.")
                        logger.info(f"User chose to schedule post {idx} via Instagram Scheduler.")
            else:
                st.warning("Image not available for this headline.")

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
    if not st.session_state.logged_in:
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

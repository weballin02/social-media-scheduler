import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth
import os
import feedparser
import requests
from datetime import datetime
from instagrapi import Client

# Import necessary libraries for Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time
import atexit

# Import Image from Pillow for handling image downloading
from PIL import Image
from io import BytesIO

# Import BeautifulSoup for HTML parsing
from bs4 import BeautifulSoup

# Import APScheduler for scheduling posts
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError

# Import pytz for timezone handling
import pytz

# Import logging module
import logging

# ----------------------------- Logging Configuration -----------------------------

# Configure logging
logging.basicConfig(
    filename='app.log',  # Log file name
    level=logging.INFO,   # Logging level
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log message format
    datefmt='%Y-%m-%d %H:%M:%S'  # Date format
)

logger = logging.getLogger(__name__)

# ----------------------------- Firebase Initialization -----------------------------

# Initialize Firebase Admin SDK
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("firebase_key.json")  # Ensure this path is correct
        firebase_admin.initialize_app(cred)
        logger.info("Firebase initialized successfully.")
    except Exception as e:
        logger.error(f"Firebase initialization failed: {e}")
        st.error(f"Firebase initialization failed: {e}")
        st.stop()

# Initialize Firestore Database
db = firestore.client()

# ----------------------------- Streamlit Configuration ------------------------------

st.set_page_config(page_title="Social Media Content Generator", layout="wide")

# ----------------------------- Session State Initialization -------------------------

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_role" not in st.session_state:
    st.session_state.user_role = None
if "rss_headlines" not in st.session_state:
    st.session_state.rss_headlines = []
if "instagram_client" not in st.session_state:
    st.session_state.instagram_client = None
if "scheduled_posts" not in st.session_state:
    st.session_state.scheduled_posts = []

# ----------------------------- Firestore Helper Functions ---------------------------

def initialize_user_metrics(email):
    """Ensure a Firestore document exists for the user."""
    doc_ref = db.collection("users").document(email)
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set({
            "rss_headlines_fetched": 0,
            "instagram_posts_scheduled": 0,
            "scheduled_posts": []
        })
        logger.info(f"Initialized Firestore metrics for user: {email}")
    else:
        logger.info(f"Firestore metrics retrieved for user: {email}")
    return doc_ref

def get_user_metrics(email):
    """Retrieve user metrics from Firestore, ensuring the document exists."""
    try:
        doc_ref = db.collection("users").document(email)
        doc = doc_ref.get()
        if doc.exists:
            metrics = doc.to_dict()
            logger.info(f"Retrieved user metrics for {email}: {metrics}")
            return metrics
        else:
            initialize_user_metrics(email)
            return {
                "rss_headlines_fetched": 0,
                "instagram_posts_scheduled": 0,
                "scheduled_posts": []
            }
    except Exception as e:
        logger.error(f"Error retrieving user metrics for {email}: {e}")
        st.error(f"Error retrieving user metrics: {e}")
        return {
            "rss_headlines_fetched": 0,
            "instagram_posts_scheduled": 0,
            "scheduled_posts": []
        }

def update_user_metric(email, metric, value):
    """Safely update a Firestore document for the user."""
    doc_ref = db.collection("users").document(email)
    doc = doc_ref.get()
    if not doc.exists:
        initialize_user_metrics(email)
    try:
        doc_ref.update({metric: firestore.Increment(value)})
        logger.info(f"Updated {metric} by {value} for user {email}.")
    except Exception as e:
        logger.error(f"Failed to update user metric '{metric}' for {email}: {e}")
        st.error(f"Failed to update user metric '{metric}': {e}")

def add_scheduled_post(email, post_data):
    """Add a scheduled post to Firestore."""
    try:
        doc_ref = db.collection("users").document(email)
        scheduled_posts = doc_ref.get().to_dict().get("scheduled_posts", [])
        scheduled_posts.append(post_data)
        doc_ref.update({"scheduled_posts": scheduled_posts})
        logger.info(f"Added scheduled post for user {email}: {post_data}")
    except Exception as e:
        logger.error(f"Failed to add scheduled post for user {email}: {e}")
        st.error(f"Failed to add scheduled post: {e}")

def remove_scheduled_post(email, post_id):
    """Remove a scheduled post from Firestore."""
    try:
        doc_ref = db.collection("users").document(email)
        scheduled_posts = doc_ref.get().to_dict().get("scheduled_posts", [])
        updated_posts = [post for post in scheduled_posts if post['id'] != post_id]
        doc_ref.update({"scheduled_posts": updated_posts})
        logger.info(f"Removed scheduled post {post_id} for user {email}.")
    except Exception as e:
        logger.error(f"Failed to remove scheduled post {post_id} for user {email}: {e}")
        st.error(f"Failed to remove scheduled post: {e}")

def update_scheduled_post(email, post_id, updated_data):
    """Update a scheduled post in Firestore."""
    try:
        doc_ref = db.collection("users").document(email)
        scheduled_posts = doc_ref.get().to_dict().get("scheduled_posts", [])
        for idx, post in enumerate(scheduled_posts):
            if post['id'] == post_id:
                scheduled_posts[idx].update(updated_data)
                break
        doc_ref.update({"scheduled_posts": scheduled_posts})
        logger.info(f"Updated scheduled post {post_id} for user {email}: {updated_data}")
    except Exception as e:
        logger.error(f"Failed to update scheduled post {post_id} for user {email}: {e}")
        st.error(f"Failed to update scheduled post: {e}")

# ----------------------------- Selenium WebDriver Initialization ---------------------

@st.cache_resource(show_spinner=False)
def init_selenium_driver():
    """Initialize and return a Selenium WebDriver using webdriver-manager."""
    try:
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless")  # Run in headless mode
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # Use webdriver-manager to handle ChromeDriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        logger.info("Selenium WebDriver initialized successfully.")
        return driver
    except Exception as e:
        logger.error(f"Selenium WebDriver initialization failed: {e}")
        st.error(f"Selenium WebDriver initialization failed: {e}")
        st.stop()

driver = init_selenium_driver()

# Ensure the driver quits when the app stops
def close_driver():
    try:
        driver.quit()
        logger.info("Selenium WebDriver closed successfully.")
    except Exception as e:
        logger.error(f"Error closing Selenium WebDriver: {e}")

atexit.register(close_driver)

def scrape_article_content(url):
    """Fetch and return the main content from an article URL."""
    try:
        driver.get(url)
        time.sleep(3)  # Wait for the page to load
        paragraphs = driver.find_elements(By.TAG_NAME, "p")
        article_content = " ".join([p.text for p in paragraphs])
        logger.info(f"Scraped article content from {url}.")
        return article_content.strip()
    except Exception as e:
        logger.error(f"Failed to fetch content from {url}: {e}")
        st.error(f"Failed to fetch content from {url}: {e}")
        return ""

# ----------------------------- Scheduler Initialization -------------------------------

@st.cache_resource(show_spinner=False)
def init_scheduler():
    """Initialize and return the APScheduler."""
    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("APScheduler initialized and started.")
    return scheduler

scheduler = init_scheduler()

# Ensure scheduler shuts down when the app stops
def shutdown_scheduler():
    try:
        scheduler.shutdown()
        logger.info("APScheduler shut down successfully.")
    except Exception as e:
        logger.error(f"Error shutting down APScheduler: {e}")

atexit.register(shutdown_scheduler)

def schedule_instagram_post(email, post_id, image_path, caption, scheduled_time):
    """Function to upload the Instagram post at the scheduled time."""
    try:
        # Initialize a new Instagram client
        client = Client()
        session_file = f"sessions/{email}.json"
        
        # Check if session file exists
        if os.path.exists(session_file):
            client.load_settings(session_file)
            client.load_session(session_file)
            client.login_by_sessionid(client.session_id)
            logger.info(f"Loaded Instagram session for user {email}.")
        else:
            logger.error(f"Instagram session file not found for user {email}.")
            st.error(f"Instagram session file not found for user {email}. Please re-login.")
            return
        
        # Upload the photo
        client.photo_upload(image_path, caption)
        logger.info(f"Scheduled Instagram post {post_id} uploaded successfully.")
        
        # Update Firestore metrics
        update_user_metric(email, "instagram_posts_scheduled", 1)
        
        # Remove the post from scheduled_posts after successful upload
        remove_scheduled_post(email, post_id)
        
    except Exception as e:
        logger.error(f"Failed to upload scheduled Instagram post {post_id}: {e}")

def add_job(email, post_id, image_path, caption, scheduled_time):
    """Add a job to the scheduler."""
    try:
        scheduler.add_job(
            schedule_instagram_post,
            'date',
            run_date=scheduled_time,
            args=[email, post_id, image_path, caption, scheduled_time],
            id=post_id,
            replace_existing=True
        )
        logger.info(f"Scheduled job {post_id} at {scheduled_time} for user {email}.")
    except Exception as e:
        logger.error(f"Failed to schedule job {post_id}: {e}")
        st.error(f"Failed to schedule post: {e}")

def load_and_schedule_existing_posts(email):
    """Load existing scheduled posts from Firestore and schedule them."""
    metrics = get_user_metrics(email)
    scheduled_posts = metrics.get("scheduled_posts", [])
    for post in scheduled_posts:
        post_id = post['id']
        image_path = post['image_path']
        caption = post['caption']
        scheduled_time = datetime.fromisoformat(post['scheduled_time'])
        timezone = post['timezone']
        scheduled_time = pytz.timezone(timezone).localize(scheduled_time)
        
        # Check if the job is already scheduled
        if not scheduler.get_job(post_id):
            if scheduled_time > datetime.now(pytz.timezone(timezone)):
                add_job(email, post_id, image_path, caption, scheduled_time)
                logger.info(f"Loaded and scheduled existing post {post_id} for user {email}.")
            else:
                # If the scheduled time is past, attempt to post immediately
                logger.info(f"Scheduled time for post {post_id} has passed. Attempting immediate upload.")
                schedule_instagram_post(email, post_id, image_path, caption, datetime.now(pytz.timezone(timezone)))

# ----------------------------- RSS Feed Functionality -------------------------------

def fetch_headlines(rss_url, limit=5, image_dir="generated_posts"):
    """Fetch and return headlines with image URLs from the RSS feed."""
    try:
        feed = feedparser.parse(rss_url)
        headlines = []
        for entry in feed.entries[:limit]:
            title = entry.title
            summary = entry.summary if 'summary' in entry else "No summary available."
            link = entry.link

            # Initialize image_url as None
            image_url = None

            # 1. Check for media:content
            if 'media_content' in entry:
                media = entry.media_content
                if isinstance(media, list) and len(media) > 0:
                    image_url = media[0].get('url', None)
                    logger.info(f"Found media_content image for headline: {title}")

            # 2. Check for media_thumbnail
            if not image_url and 'media_thumbnail' in entry:
                media_thumbnails = entry.media_thumbnail
                if isinstance(media_thumbnails, list) and len(media_thumbnails) > 0:
                    image_url = media_thumbnails[0].get('url', None)
                    logger.info(f"Found media_thumbnail image for headline: {title}")

            # 3. Check for enclosure
            if not image_url and 'enclosures' in entry:
                enclosures = entry.enclosures
                for enclosure in enclosures:
                    if enclosure.get('type', '').startswith('image/'):
                        image_url = enclosure.get('url', None)
                        logger.info(f"Found enclosure image for headline: {title}")
                        break  # Take the first image found

            # 4. Check for image in summary/content using BeautifulSoup
            if not image_url and 'summary' in entry:
                summary_html = entry.summary
                soup = BeautifulSoup(summary_html, 'html.parser')
                img_tag = soup.find('img')
                if img_tag and img_tag.get('src'):
                    image_url = img_tag.get('src')
                    logger.info(f"Found embedded image in summary for headline: {title}")

            # Download the image if image_url is found
            image_path = None
            if image_url:
                image_path = download_image(image_url, image_dir=image_dir)
                if image_path:
                    logger.info(f"Image downloaded and saved at {image_path} for headline: {title}")
                else:
                    logger.warning(f"Image download failed for headline: {title}")
            else:
                logger.warning(f"No image found for headline: {title}")

            # Append the headline data
            headlines.append({
                "title": title,
                "summary": summary,
                "link": link,
                "image_url": image_url,
                "image_path": image_path
            })
        logger.info(f"Fetched {len(headlines)} headlines from {rss_url}.")
        return headlines
    except Exception as e:
        logger.error(f"Failed to fetch RSS feed from {rss_url}: {e}")
        st.error(f"Failed to fetch RSS feed: {e}")
        return []

def download_image(image_url, image_dir="generated_posts"):
    """Download an image from a URL and save it locally."""
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()  # Raise an exception for HTTP errors
        img = Image.open(BytesIO(response.content)).convert("RGB")

        # Ensure the image directory exists
        if not os.path.exists(image_dir):
            os.makedirs(image_dir)
            logger.info(f"Created directory: {image_dir}")

        # Define image path with timestamp and unique identifier
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')  # Including microseconds for uniqueness
        image_filename = f"ig_post_{timestamp}.jpg"
        image_path = os.path.join(image_dir, image_filename)

        # Save the image
        img.save(image_path)
        logger.info(f"Image downloaded from {image_url} and saved at {image_path}")
        return image_path
    except Exception as e:
        logger.error(f"Failed to download image from {image_url}: {e}")
        st.error(f"Failed to download image from {image_url}: {e}")
        return None

# ----------------------------- Instagram Scheduler Functionality ---------------------

def render_instagram_scheduler_page():
    st.header("📅 Instagram Scheduler")
    st.subheader("Plan and Automate Your Instagram Content")

    username = st.text_input("Instagram Username")
    password = st.text_input("Instagram Password", type="password")
    image_directory = st.text_input("Image Directory", "generated_posts")
    timezone = st.selectbox("Select Timezone", pytz.all_timezones, index=pytz.all_timezones.index('UTC'))

    if st.button("Login to Instagram"):
        if not username or not password:
            st.error("Please provide Instagram credentials!")
            logger.warning("Instagram login attempted without credentials.")
        else:
            try:
                client = Client()
                client.login(username, password)
                st.session_state.instagram_client = client

                # Save session to file for persistence
                if not os.path.exists("sessions"):
                    os.makedirs("sessions")
                session_file = f"sessions/{username}.json"
                client.dump_settings(session_file)
                client.dump_session(session_file)
                logger.info(f"User {username} logged into Instagram successfully and session saved.")
                st.success("Logged into Instagram and session saved!")
            except Exception as e:
                st.error(f"Login failed: {e}")
                logger.error(f"Instagram login failed for user {username}: {e}")

    st.markdown("---")

    st.subheader("📅 Schedule New Instagram Posts")

    # Fetch user metrics to get scheduled posts
    if st.session_state.user_email:
        metrics = get_user_metrics(st.session_state.user_email)
        scheduled_posts = metrics.get("scheduled_posts", [])
    else:
        scheduled_posts = []

    # Fetch all headlines
    fetched_headlines = st.session_state.rss_headlines

    # Retrieve scheduled post captions to prevent duplicate scheduling
    scheduled_captions = [post.get('caption', '').replace(f" Read more at: {post.get('article_url', '')}", '') for post in scheduled_posts]

    # Determine unscheduled headlines
    unscheduled_headlines = [
        headline for headline in fetched_headlines
        if headline['title'] not in scheduled_captions
    ]

    if not unscheduled_headlines:
        st.info("No unscheduled posts available. Fetch more headlines or schedule existing posts.")
        return

    # Create a mapping from titles to headlines
    title_to_headline = {headline['title']: headline for headline in unscheduled_headlines}

    # Multiselect dropdown for unscheduled posts
    selected_titles = st.multiselect(
        "Select Post(s) to Schedule",
        options=list(title_to_headline.keys()),
        format_func=lambda x: x  # Display titles as they are
    )

    if selected_titles:
        for title in selected_titles:
            headline = title_to_headline[title]
            st.markdown(f"### {headline['title']}")
            if headline['image_path'] and os.path.exists(headline['image_path']):
                st.image(headline['image_path'], caption="Fetched Image", use_container_width=True)
            else:
                st.warning("No image available for this headline.")

            # Create a form for each post
            with st.form(key=f"schedule_form_{title}", clear_on_submit=False):
                # Select date and time for each post
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
                        logger.warning("Attempted to schedule post without Instagram login.")
                    else:
                        # Combine date and time with timezone
                        try:
                            scheduled_datetime = datetime.combine(scheduled_date, scheduled_time)
                            scheduled_datetime = pytz.timezone(timezone).localize(scheduled_datetime)
                        except Exception as e:
                            st.error(f"Error in scheduling datetime: {e}")
                            logger.error(f"Error in scheduling datetime for post '{title}': {e}")
                            continue

                        # Check if scheduled_datetime is in the future
                        now = datetime.now(pytz.timezone(timezone))
                        if scheduled_datetime <= now:
                            st.error("Scheduled time must be in the future!")
                            logger.warning(f"User attempted to schedule post '{title}' in the past.")
                            continue

                        # Generate a unique ID for the scheduled post
                        post_id = f"{st.session_state.user_email}_{int(time.time())}_{title.replace(' ', '_')}"

                        # Prepare caption with article URL
                        if headline['link']:
                            full_caption = f"{caption}\nRead more at: {headline['link']}"
                        else:
                            full_caption = caption  # If no link is available

                        # Prepare post data
                        post_data = {
                            "id": post_id,
                            "image_path": headline['image_path'],
                            "caption": full_caption,
                            "scheduled_time": scheduled_datetime.isoformat(),
                            "timezone": timezone,
                            "article_url": headline['link'] if headline['link'] else ""
                        }

                        # Add the post to Firestore
                        add_scheduled_post(st.session_state.user_email, post_data)

                        # Schedule the post using APScheduler
                        add_job(
                            st.session_state.user_email,
                            post_id,
                            headline['image_path'],
                            full_caption,
                            scheduled_datetime
                        )

                        st.success(f"Post '{title}' scheduled successfully for {scheduled_datetime.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        logger.info(f"Post '{post_id}' scheduled for {scheduled_datetime} by user {st.session_state.user_email}.")

    st.markdown("---")

    st.subheader("📋 Your Scheduled Posts")

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
                        st.markdown(f"**Article URL:** Not available")
                    # Edit and Delete buttons
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button(f"Edit {post['id']}", key=f"edit_{post['id']}"):
                            edit_scheduled_post(email=st.session_state.user_email, post=post)
                    with col_b:
                        if st.button(f"Delete {post['id']}", key=f"delete_{post['id']}"):
                            delete_scheduled_post(email=st.session_state.user_email, post_id=post['id'])
    else:
        st.info("No scheduled posts found.")

def edit_scheduled_post(email, post):
    """Provide a form to edit a scheduled post."""
    with st.form(f"edit_form_{post['id']}"):
        st.header(f"Edit Scheduled Post {post['id']}")

        # Extract the original caption without the article URL
        original_caption = post['caption']
        article_url = post.get('article_url', '')
        if article_url:
            # Remove the 'Read more at: <URL>' part
            original_caption = original_caption.replace(f"\nRead more at: {article_url}", '')

        new_caption = st.text_area("Post Caption", original_caption, key=f"edit_caption_{post['id']}")

        # Parse the scheduled time
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
            # Combine date and time with timezone
            try:
                new_scheduled_datetime = datetime.combine(new_date, new_time)
                new_scheduled_datetime = pytz.timezone(new_timezone).localize(new_scheduled_datetime)
            except Exception as e:
                st.error(f"Error in scheduling datetime: {e}")
                logger.error(f"Error in scheduling datetime for post '{post['id']}': {e}")
                return

            # Check if new_scheduled_datetime is in the future
            now = datetime.now(pytz.timezone(new_timezone))
            if new_scheduled_datetime <= now:
                st.error("Scheduled time must be in the future!")
                logger.warning(f"User attempted to update post '{post['id']}' to a past time.")
                return

            # Prepare updated caption with article URL
            if post.get('article_url'):
                updated_caption = f"{new_caption}\nRead more at: {post['article_url']}"
            else:
                updated_caption = new_caption  # If no link is available

            # Update Firestore
            updated_data = {
                "caption": updated_caption,
                "scheduled_time": new_scheduled_datetime.isoformat(),
                "timezone": new_timezone
            }
            update_scheduled_post(email, post['id'], updated_data)

            # Reschedule the job
            try:
                scheduler.remove_job(post['id'])
                logger.info(f"Removed existing job {post['id']} for rescheduling.")
            except JobLookupError:
                logger.warning(f"Job {post['id']} not found in scheduler for removal.")

            add_job(
                email,
                post['id'],
                post['image_path'],
                updated_caption,
                new_scheduled_datetime
            )

            st.success("Scheduled post updated successfully!")
            logger.info(f"Scheduled post {post['id']} updated to {new_scheduled_datetime} by user {email}.")

def delete_scheduled_post(email, post_id):
    """Delete a scheduled post."""
    try:
        scheduler.remove_job(post_id)
        logger.info(f"Removed job {post_id} from scheduler.")
    except JobLookupError:
        logger.warning(f"Job {post_id} not found in scheduler for removal.")

    remove_scheduled_post(email, post_id)
    st.success(f"Scheduled post {post_id} deleted successfully.")
    logger.info(f"Scheduled post {post_id} deleted by user {email}.")

# ----------------------------- Dashboard Rendering -----------------------------------

def render_dashboard(metrics, thresholds):
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

    # RSS Headlines Fetched
    render_metric_card(
        col1,
        "RSS Headlines Fetched",
        metrics.get("rss_headlines_fetched", 0),
        thresholds.get("rss_headlines_fetched", 10),
        "https://img.icons8.com/color/64/000000/rss.png",
        "#4CAF50" if metrics.get("rss_headlines_fetched", 0) < thresholds.get("rss_headlines_fetched", 10) else "#FF5722",
    )

    # Instagram Posts Scheduled
    render_metric_card(
        col2,
        "Instagram Posts Scheduled",
        metrics.get("instagram_posts_scheduled", 0),
        thresholds.get("instagram_posts_scheduled", 5),
        "https://img.icons8.com/color/64/000000/instagram-new.png",
        "#4CAF50" if metrics.get("instagram_posts_scheduled", 0) < thresholds.get("instagram_posts_scheduled", 5) else "#FF5722",
    )

    # Upgrade Suggestion
    if st.session_state.user_role == "free":
        if metrics.get("rss_headlines_fetched", 0) >= thresholds.get("rss_headlines_fetched", 10):
            st.warning("Upgrade to Premium to fetch more RSS headlines!")
        if metrics.get("instagram_posts_scheduled", 0) >= thresholds.get("instagram_posts_scheduled", 5):
            st.warning("Upgrade to Premium to schedule more Instagram posts!")

# ----------------------------- RSS Feeds Rendering ------------------------------------

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
        # Clear previous headlines to prevent duplication
        st.session_state.rss_headlines = []
        headlines = fetch_headlines(rss_url, limit=num_headlines)
        if headlines:
            progress_text = "Fetching RSS headlines and downloading images..."
            progress_bar = st.progress(0, text=progress_text)
            total_headlines = len(headlines)
            for idx, entry in enumerate(headlines):
                st.markdown(f"### [{entry['title']}]({entry['link']})")
                st.write(entry['summary'])
                # Display the downloaded image if available
                if entry['image_path']:
                    st.image(entry['image_path'], caption="Fetched Image", use_container_width=True)
                    # Append to session state
                    st.session_state.rss_headlines.append({
                        "title": entry['title'],
                        "summary": entry['summary'],
                        "link": entry['link'],
                        "image_url": entry['image_url'],
                        "image_path": entry['image_path']
                    })
                else:
                    st.warning("No image available for this headline.")
                update_user_metric(st.session_state.user_email, "rss_headlines_fetched", 1)
                progress = (idx + 1) / total_headlines
                progress_bar.progress(progress, text=f"{int(progress*100)}% Completed")
                time.sleep(0.5)  # Simulate delay
            progress_bar.empty()
            st.success("RSS headlines fetched and images downloaded successfully!")
        else:
            st.warning("No headlines found. Try another feed.")

    # Display generated IG posts from fetched headlines
    if st.session_state.rss_headlines:
        st.markdown("## 📸 Generated Instagram Posts from Headlines")
        for idx, post in enumerate(st.session_state.rss_headlines, 1):
            st.markdown(f"### Post {idx}")
            if 'image_path' in post and post['image_path']:
                st.image(post['image_path'], caption=post['title'], use_container_width=True)
                if st.button(f"Schedule Post {idx}", key=f"schedule_{idx}"):
                    if "instagram_client" not in st.session_state or not st.session_state.instagram_client:
                        st.error("Please login to Instagram first.")
                        logger.warning("Attempted to schedule post without Instagram login.")
                    else:
                        try:
                            caption = post['title']  # Use the headline as the caption
                            # Default to current time if no scheduling is done here
                            # However, since scheduling is handled separately, we'll just prepare data
                            # The user should use the Instagram Scheduler page to schedule
                            st.success("Please use the 'Instagram Scheduler' page to schedule this post.")
                            logger.info(f"User attempted to schedule post {idx} without proper scheduling process.")
                        except Exception as e:
                            st.error(f"Failed to schedule post {idx}: {e}")
                            logger.error(f"Failed to schedule Instagram post {post['image_path']}: {e}")
            else:
                st.warning("Image not available for this headline.")
                logger.warning(f"No image path available for post: {post['title']}")

# ----------------------------- User Interface Rendering ------------------------------

def render_user_interface():
    menu = st.sidebar.radio("Navigation", ["Dashboard", "RSS Feeds", "Instagram Scheduler"])

    thresholds = {
        "rss_headlines_fetched": 10,
        "instagram_posts_scheduled": 5,
    }

    if menu == "Dashboard":
        metrics = get_user_metrics(st.session_state.user_email)
        render_dashboard(metrics, thresholds)

    elif menu == "RSS Feeds":
        render_rss_feeds_page()

    elif menu == "Instagram Scheduler":
        render_instagram_scheduler_page()

# ----------------------------- Authentication Functions -------------------------------

def register_user():
    st.header("Register")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    confirm_password = st.text_input("Confirm Password", type="password")
    if st.button("Register"):
        if not email or not password or not confirm_password:
            st.error("Please fill out all fields!")
            logger.warning("User attempted registration without filling all fields.")
        elif password != confirm_password:
            st.error("Passwords do not match!")
            logger.warning(f"User registration failed: Passwords do not match for email {email}.")
        elif len(password) < 6:
            st.error("Password must be at least 6 characters long.")
            logger.warning(f"User registration failed: Password too short for email {email}.")
        else:
            try:
                user = auth.create_user(email=email, password=password)
                auth.set_custom_user_claims(user.uid, {"role": "free"})
                initialize_user_metrics(email)
                st.success("Registration successful! Please log in.")
                logger.info(f"User registered successfully: {email}")
            except Exception as e:
                st.error(f"Registration failed: {e}")
                logger.error(f"Registration failed for email {email}: {e}")

def login_user():
    st.header("Login")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if not email or not password:
            st.error("Please provide both email and password!")
            logger.warning("User attempted login without providing email or password.")
        else:
            try:
                user = auth.get_user_by_email(email)
                # Note: Firebase Admin SDK does not handle password verification.
                # Password verification should be handled on the client side or using Firebase Authentication client SDK.
                # Here, we assume successful login for demonstration purposes.
                st.session_state.user_email = email
                st.session_state.user_role = user.custom_claims.get("role", "free")
                st.session_state.logged_in = True
                initialize_user_metrics(email)
                st.success(f"Logged in as {st.session_state.user_role} user!")
                logger.info(f"User logged in successfully: {email}")

                # Load and schedule existing posts
                load_and_schedule_existing_posts(email)

            except firebase_admin.auth.UserNotFoundError:
                st.error("User not found. Please register.")
                logger.warning(f"Login failed: User not found for email {email}.")
            except Exception as e:
                st.error(f"Login failed: {e}")
                logger.error(f"Login failed for email {email}: {e}")

# ----------------------------- Main Application Logic ---------------------------------

def main():
    st.title("🚀 Social Media Content Generator")

    # Authentication Section
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

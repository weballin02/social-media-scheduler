"""
Local Social Media Content Generator with Monetization
(Production-Ready Version with Top Navigation Bar, Option 2 Palette, and State–Based Routing)
"""

import os
import json
import time
import threading
import atexit
import logging
from datetime import datetime

import streamlit as st
import feedparser
import requests
from instagrapi import Client
from PIL import Image
from io import BytesIO
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
import pytz
import stripe

# ----------------------------- Load Environment Variables -----------------------------
from dotenv import load_dotenv
load_dotenv()  # Loads configuration from .env file

# ----------------------------- Global Configuration -----------------------------
TEST_MODE = os.getenv("TEST_MODE", "False").lower() in ("true", "1", "t")
PRICING_TIERS = {
    "Premium": 9.99,
    "Pro": 19.99
}

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
if not STRIPE_SECRET_KEY:
    logging.error("STRIPE_SECRET_KEY is not set in the environment variables.")
stripe.api_key = STRIPE_SECRET_KEY

# ----------------------------- Logging Configuration -----------------------------
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ----------------------------- Database Setup -----------------------------
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.exc import SQLAlchemyError

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    email = Column(String, primary_key=True, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="free")
    metrics = relationship("UserMetric", back_populates="user", uselist=False)
    posts = relationship("ScheduledPost", back_populates="user")

class UserMetric(Base):
    __tablename__ = "user_metrics"
    email = Column(String, ForeignKey("users.email"), primary_key=True)
    rss_headlines_fetched = Column(Integer, default=0)
    instagram_posts_scheduled = Column(Integer, default=0)
    user = relationship("User", back_populates="metrics")

class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    id = Column(String, primary_key=True, index=True)
    email = Column(String, ForeignKey("users.email"))
    image_path = Column(String)
    caption = Column(Text)
    scheduled_time = Column(DateTime)
    timezone = Column(String)
    article_url = Column(String)
    user = relationship("User", back_populates="posts")

def init_db():
    Base.metadata.create_all(engine)

# ----------------------------- Password Hashing -----------------------------
from passlib.hash import bcrypt

# ----------------------------- Streamlit Configuration -----------------------------
st.set_page_config(page_title="🚀 Social Media Content Generator", layout="wide")

# ----------------------------- Custom CSS for Option 2 Palette -----------------------------
st.markdown(
    """
    <style>
    :root {
        /* Primary color for main navigation and primary buttons */
        --primary-color: #5B4CF5;
        /* Secondary color for interactive elements, hover states, etc. */
        --secondary-color: #2E7DFF;
        /* Accent colors for success and error states */
        --success-color: #10B981;
        --error-color: #FF7070;
        /* Dark theme background for overall app */
        --background-color: #121212;
        /* Card background */
        --card-background: #1E1E1E;
        /* Text color */
        --text-color: #E0E0E0;
    }

    /* Main container background */
    .reportview-container {
        background: var(--background-color);
    }

    /* Top navigation bar styling */
    .top-nav {
        padding: 0.5em 1em;
        background: var(--card-background);
        border-bottom: 1px solid #444;
        margin-bottom: 1em;
    }
    .top-nav button {
        background-color: var(--primary-color);
        color: white;
        border: none;
        border-radius: 4px;
        padding: 0.5em 1em;
        margin-right: 0.5em;
        font-size: 16px;
    }
    .top-nav button:hover {
        background-color: var(--secondary-color);
    }

    /* Button styling (for non-nav buttons) */
    .stButton button {
        background-color: var(--primary-color);
        color: white;
        border: none;
        border-radius: 4px;
        padding: 0.5em 1em;
        font-size: 16px;
    }
    .stButton button:hover {
        background-color: var(--secondary-color);
    }

    /* Text input styling */
    .stTextInput > div > input {
        border: 1px solid #444;
        border-radius: 4px;
        padding: 0.5em;
        color: var(--text-color);
        background: var(--card-background);
    }

    /* Metric card styling */
    .metric-card {
        text-align: center;
        border: 1px solid #444;
        padding: 15px;
        border-radius: 10px;
        background: var(--card-background);
        color: var(--text-color);
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ----------------------------- Session State Initialization -----------------------------
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
if "ig_username" not in st.session_state:
    st.session_state.ig_username = None
if "ig_password" not in st.session_state:
    st.session_state.ig_password = None

# ----------------------------- APScheduler Initialization -----------------------------
@st.cache_resource(show_spinner=False)
def init_scheduler():
    scheduler_ = BackgroundScheduler()
    scheduler_.start()
    logger.info("APScheduler started.")
    return scheduler_

scheduler = init_scheduler()
atexit.register(lambda: scheduler.shutdown())

# ----------------------------- Database-Based Helper Functions -----------------------------
def register_user_local(email, password):
    with SessionLocal() as db:
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            st.error("User already exists. Please log in.")
            return False
        password_hash = bcrypt.hash(password)
        user = User(email=email, password_hash=password_hash, role="free")
        db.add(user)
        metrics = UserMetric(email=email, rss_headlines_fetched=0, instagram_posts_scheduled=0)
        db.add(metrics)
        try:
            db.commit()
            st.success("Registration successful! Please log in.")
            logger.info(f"User registered: {email}")
            return True
        except SQLAlchemyError as e:
            db.rollback()
            st.error(f"Database error during registration: {e}")
            logger.error(f"Database error during registration for {email}: {e}")
            return False

def login_user_local(email, password):
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            st.error("User not found. Please register.")
            return False
        if not bcrypt.verify(password, user.password_hash):
            st.error("Incorrect password.")
            return False
        st.session_state.user_email = email
        st.session_state.user_role = user.role
        st.session_state.logged_in = True
        st.success(f"Logged in as {user.role} user!")
        logger.info(f"User logged in: {email}")
        load_and_schedule_existing_posts(email)
        return True

def upgrade_user_plan(username, plan):
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == username).first()
        if user:
            user.role = plan
            try:
                db.commit()
                st.session_state.user_role = plan
                logger.info(f"User {username} upgraded to {plan}")
            except SQLAlchemyError as e:
                db.rollback()
                st.error("Database error during upgrade.")
                logger.error(f"Database error during upgrade for {username}: {e}")
        else:
            st.error("User not found during upgrade.")

def update_user_metric(email, metric, value):
    with SessionLocal() as db:
        user_metric = db.query(UserMetric).filter(UserMetric.email == email).first()
        if not user_metric:
            user_metric = UserMetric(email=email, rss_headlines_fetched=0, instagram_posts_scheduled=0)
            db.add(user_metric)
        if hasattr(user_metric, metric):
            setattr(user_metric, metric, getattr(user_metric, metric, 0) + value)
        else:
            st.error("Invalid metric specified.")
            return
        try:
            db.commit()
            logger.info(f"Updated {metric} by {value} for user {email}.")
        except SQLAlchemyError as e:
            db.rollback()
            st.error("Database error during metric update.")
            logger.error(f"Database error during metric update for {email}: {e}")

def get_user_metrics(email):
    with SessionLocal() as db:
        user_metric = db.query(UserMetric).filter(UserMetric.email == email).first()
        if user_metric:
            return {
                "rss_headlines_fetched": user_metric.rss_headlines_fetched,
                "instagram_posts_scheduled": user_metric.instagram_posts_scheduled,
            }
        return {"rss_headlines_fetched": 0, "instagram_posts_scheduled": 0}

def add_scheduled_post(email, post_data):
    with SessionLocal() as db:
        post = ScheduledPost(
            id=post_data["id"],
            email=email,
            image_path=post_data["image_path"],
            caption=post_data["caption"],
            scheduled_time=datetime.fromisoformat(post_data["scheduled_time"]),
            timezone=post_data["timezone"],
            article_url=post_data.get("article_url", "")
        )
        db.add(post)
        try:
            db.commit()
            logger.info(f"Added scheduled post for user {email}: {post_data}")
        except SQLAlchemyError as e:
            db.rollback()
            st.error("Database error during adding scheduled post.")
            logger.error(f"Database error during adding scheduled post for {email}: {e}")

def remove_scheduled_post(email, post_id):
    with SessionLocal() as db:
        post = db.query(ScheduledPost).filter(ScheduledPost.id == post_id, ScheduledPost.email == email).first()
        if post:
            db.delete(post)
            try:
                db.commit()
                logger.info(f"Removed scheduled post {post_id} for user {email}.")
            except SQLAlchemyError as e:
                db.rollback()
                st.error("Database error during removing scheduled post.")
                logger.error(f"Database error during removing scheduled post for {email}: {e}")

def update_scheduled_post(email, post_id, updated_data):
    with SessionLocal() as db:
        post = db.query(ScheduledPost).filter(ScheduledPost.id == post_id, ScheduledPost.email == email).first()
        if post:
            if "caption" in updated_data:
                post.caption = updated_data["caption"]
            if "scheduled_time" in updated_data:
                post.scheduled_time = datetime.fromisoformat(updated_data["scheduled_time"])
            if "timezone" in updated_data:
                post.timezone = updated_data["timezone"]
            try:
                db.commit()
                logger.info(f"Updated scheduled post {post_id} for user {email}: {updated_data}")
            except SQLAlchemyError as e:
                db.rollback()
                st.error("Database error during updating scheduled post.")
                logger.error(f"Database error during updating scheduled post for {email}: {e}")

def load_and_schedule_existing_posts(email):
    with SessionLocal() as db:
        scheduled_posts = db.query(ScheduledPost).filter(ScheduledPost.email == email).all()
    for post in scheduled_posts:
        post_id = post.id
        image_path = post.image_path
        caption = post.caption
        scheduled_time = post.scheduled_time
        timezone_str = post.timezone
        try:
            timezone = pytz.timezone(timezone_str)
            if scheduled_time.tzinfo is None:
                scheduled_time = timezone.localize(scheduled_time)
        except Exception as e:
            logger.error(f"Timezone error for post {post_id}: {e}")
            continue
        if not scheduler.get_job(post_id):
            now_in_zone = datetime.now(pytz.timezone(timezone_str))
            if scheduled_time > now_in_zone:
                add_job(email, post_id, image_path, caption, scheduled_time)
                logger.info(f"Loaded and scheduled post {post_id} for {email}")
            else:
                logger.info(f"Post {post_id} time has passed. Uploading immediately.")
                schedule_instagram_post(email, post_id, image_path, caption, now_in_zone)

# ----------------------------- Page Functions -----------------------------
def render_dashboard(metrics, thresholds):
    st.header("📊 Dashboard")
    st.subheader("Your Activity Overview")
    col1, col2 = st.columns(2)
    def render_metric_card(column, label, current, total, icon_url, progress_color):
        with column:
            st.markdown(
                f"""
                <div class="metric-card">
                    <img src="{icon_url}" alt="{label}" style="width:50px; height:50px; margin-bottom:10px;" />
                    <h3 style="margin: 5px 0;">{label}</h3>
                    <p style="margin: 5px 0; font-size: 18px;">{current} / {total}</p>
                    <div style="height: 20px; background-color: #90A4AE; border-radius: 10px;">
                        <div style="width: {min(current / total * 100, 100)}%; background-color: {progress_color}; height: 100%; border-radius: 10px;"></div>
                    </div>
                    <p style="margin: 5px 0; font-size: 14px;">{int(current / total * 100)}% Completed</p>
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

def render_rss_feeds_page():
    st.header("📰 RSS Feeds")
    st.subheader("Explore the Latest News and Create Instagram Posts")
    rss_feeds = {
        "BBC News (World)": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "CNN Top Stories": "http://rss.cnn.com/rss/cnn_topstories.rss",
        "Reuters Top News": "http://feeds.reuters.com/reuters/topNews",
        "NYT: Home Page": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "The Guardian (UK)": "https://www.theguardian.com/uk/rss",
        "ESPN Top Headlines": "https://www.espn.com/espn/rss/news",
        "TechCrunch": "http://feeds.feedburner.com/TechCrunch/",
        "The Verge": "https://www.theverge.com/rss/index.xml",
        "MarketWatch": "http://feeds.marketwatch.com/marketwatch/topstories/"
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
                    if not st.session_state.instagram_client:
                        st.error("Please login to Instagram first.")
                        logger.warning("Attempted scheduling without Instagram login.")
                    else:
                        st.success("Please use the 'Instagram Scheduler' page to schedule this post.")
                        logger.info(f"User chose to schedule post {idx} via Instagram Scheduler.")
            else:
                st.warning("Image not available for this headline.")

def render_instagram_scheduler_page():
    st.header("📅 Instagram Scheduler")
    st.subheader("Plan and Automate Your Instagram Content")
    username = st.text_input("Instagram Username", value=st.session_state.ig_username or "")
    password = st.text_input("Instagram Password", type="password", value=st.session_state.ig_password or "")
    image_directory = st.text_input("Image Directory", "generated_posts")
    timezone = st.selectbox("Select Timezone", pytz.all_timezones, index=pytz.all_timezones.index('UTC'))
    if st.button("Login to Instagram"):
        if not username or not password:
            st.error("Please provide Instagram credentials!")
            logger.warning("Instagram login attempted without credentials.")
        else:
            success = login_to_instagram(username, password)
            if success:
                st.session_state.ig_username = username
                st.session_state.ig_password = password
                st.session_state.instagram_client = client
                st.success("Logged into Instagram and session saved!")
                logger.info(f"User {username} logged into Instagram; session saved.")
            else:
                st.error("Login failed. Check logs for details.")
    st.markdown("---")
    st.subheader("📅 Schedule New Instagram Posts")
    if st.session_state.user_email:
        metrics = get_user_metrics(st.session_state.user_email)
        with SessionLocal() as db:
            scheduled_posts = db.query(ScheduledPost).filter(ScheduledPost.email == st.session_state.user_email).all()
    else:
        scheduled_posts = []
    fetched_headlines = st.session_state.rss_headlines
    scheduled_captions = [post.caption.replace(f" Read more at: {post.article_url}", '') for post in scheduled_posts]
    unscheduled_headlines = [h for h in fetched_headlines if h['title'] not in scheduled_captions]
    if not unscheduled_headlines:
        st.info("No unscheduled posts available. Fetch more headlines or schedule existing posts.")
        return
    title_to_headline = {headline['title']: headline for headline in unscheduled_headlines}
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
                        now_in_zone = datetime.now(pytz.timezone(timezone))
                        if scheduled_datetime <= now_in_zone:
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
    st.subheader("📋 Your Scheduled Posts")
    if scheduled_posts:
        for post in scheduled_posts:
            with st.expander(f"Post ID: {post.id}"):
                col1, col2 = st.columns([1, 2])
                with col1:
                    if post.image_path and os.path.exists(post.image_path):
                        st.image(post.image_path, use_container_width=True)
                    else:
                        st.warning("Image not available.")
                with col2:
                    st.markdown(f"**Caption:** {post.caption}")
                    st_time = post.scheduled_time
                    st.markdown(f"**Scheduled Time:** {st_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    if post.article_url:
                        st.markdown(f"**Article URL:** [Read more]({post.article_url})")
                    else:
                        st.markdown("**Article URL:** Not available")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button(f"Edit {post.id}", key=f"edit_{post.id}"):
                            edit_scheduled_post(email=st.session_state.user_email, post=post)
                    with col_b:
                        if st.button(f"Delete {post.id}", key=f"delete_{post.id}"):
                            delete_scheduled_post(email=st.session_state.user_email, post_id=post.id)
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

# ----------------------------- Authentication UI -----------------------------
def login_form():
    st.header("Login")
    email = st.text_input("Email", key="login_email")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Login"):
        if not email or not password:
            st.error("Please provide both email and password!")
        else:
            success = login_user_local(email, password)
            if success:
                st.rerun()
            else:
                st.error("Login failed. Please try again.")

def register_form():
    st.header("Register")
    email = st.text_input("Email", key="register_email")
    password = st.text_input("Password", type="password", key="register_password")
    confirm_password = st.text_input("Confirm Password", type="password", key="register_confirm_password")
    if st.button("Register"):
        if not email or not password or not confirm_password:
            st.error("Please fill out all fields!")
        elif password != confirm_password:
            st.error("Passwords do not match!")
        elif len(password) < 6:
            st.error("Password must be at least 6 characters long.")
        else:
            success = register_user_local(email, password)
            if success:
                st.success("Registration successful! You can now log in.")
                st.session_state.auth_mode = "login"
                st.rerun()
            else:
                st.error("Registration failed. Please try again.")

def auth_page():
    if "auth_mode" not in st.session_state:
        st.session_state.auth_mode = "login"
    if st.session_state.auth_mode == "login":
        login_form()
        if st.button("Don't have an account? Register"):
            st.session_state.auth_mode = "register"
            st.rerun()
    elif st.session_state.auth_mode == "register":
        register_form()
        if st.button("Already have an account? Log in"):
            st.session_state.auth_mode = "login"
            st.rerun()

# ----------------------------- Top Navigation and Page Routing -----------------------------
def render_nav():
    nav_cols = st.columns(4)
    with nav_cols[0]:
        if st.button("📊 Dashboard"):
            return "Dashboard"
    with nav_cols[1]:
        if st.button("📰 RSS Feeds"):
            return "RSS Feeds"
    with nav_cols[2]:
        if st.button("📸 Instagram"):
            return "Instagram Scheduler"
    with nav_cols[3]:
        if st.button("⭐ Upgrade"):
            return "Upgrade"
    return st.session_state.get("current_page", "Dashboard")

def render_user_interface():
    current_page = st.session_state.current_page
    if current_page == "Dashboard":
        thresholds = {"rss_headlines_fetched": 10, "instagram_posts_scheduled": 5}
        metrics = get_user_metrics(st.session_state.user_email)
        render_dashboard(metrics, thresholds)
    elif current_page == "RSS Feeds":
        render_rss_feeds_page()
    elif current_page == "Instagram Scheduler":
        render_instagram_scheduler_page()
    elif current_page == "Upgrade":
        render_upgrade_page()

# ----------------------------- Main Application Logic -----------------------------
def main():
    init_db()
    st.title("🚀 Social Media Content Generator")
    if not st.session_state.get("logged_in", False):
        auth_page()
    else:
        # Top Navigation: render nav bar and update current page state
        if "current_page" not in st.session_state:
            st.session_state.current_page = "Dashboard"
        current_page = render_nav()
        if current_page != st.session_state.current_page:
            st.session_state.current_page = current_page
            st.rerun()
        # Render the page based on the current page state
        render_user_interface()

if __name__ == "__main__":
    main()

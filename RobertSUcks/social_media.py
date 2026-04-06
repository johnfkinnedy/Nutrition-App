from flask import Blueprint, session, redirect, url_for, render_template_string, request
import mysql.connector
import json
import uuid
from pathlib import Path
from werkzeug.utils import secure_filename

social_bp = Blueprint("social", __name__, url_prefix="/social")

DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "Barker123!",
    "database": "NutriLog",
}

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SOCIAL_UPLOAD_DIR = STATIC_DIR / "social_uploads"
SOCIAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

def _db_conn():
    return mysql.connector.connect(**DB_CONFIG)

def _require_login():
    return session.get("user_id") is not None

def _parse_posts_json(val):
    if val is None:
        return []

    if isinstance(val, (bytes, bytearray)):
        try:
            val = val.decode("utf-8", errors="ignore")
        except Exception:
            return []

    if isinstance(val, str):
        try:
            out = json.loads(val)
            if isinstance(out, list):
                return [str(x) for x in out if isinstance(x, str)]
            return []
        except Exception:
            return []

    if isinstance(val, list):
        return [str(x) for x in val if isinstance(x, str)]

    return []

def _latest_post_text(posts_arr):
    if isinstance(posts_arr, list) and len(posts_arr) > 0:
        return posts_arr[-1]
    return ""

def _clean_tag_ids(tagged_user_ids):
    clean = []
    for x in tagged_user_ids:
        try:
            tag_id = int(x)
            if tag_id not in clean:
                clean.append(tag_id)
        except Exception:
            pass
    return clean

def _save_uploaded_image(file_storage):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None

    original_name = secure_filename(file_storage.filename or "")
    if not original_name:
        return None

    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return None

    out_name = f"{uuid.uuid4().hex}_{Path(original_name).stem}{ext}"
    out_path = SOCIAL_UPLOAD_DIR / out_name
    file_storage.save(out_path)
    return out_name

def _fetch_all_users():
    conn = None
    cur = None
    users = []

    try:
        conn = _db_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT user_id, first_name, last_name
            FROM Users
            ORDER BY first_name ASC, last_name ASC, user_id ASC
            """
        )
        rows = cur.fetchall() or []

        for r in rows:
            users.append({
                "user_id": r["user_id"],
                "user_name": f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip()
            })
    except Exception as e:
        session["flash_msg"] = f"Error loading users: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return users

def _fetch_following_and_suggestions(current_user_id):
    conn = None
    cur = None
    following = []
    suggestions = []

    try:
        conn = _db_conn()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT
                u.user_id,
                u.first_name,
                u.last_name
            FROM Social_Follows sf
            INNER JOIN Users u
                ON sf.followed_user_id = u.user_id
            WHERE sf.follower_user_id = %s
            ORDER BY u.first_name ASC, u.last_name ASC, u.user_id ASC
            """,
            (current_user_id,)
        )
        rows = cur.fetchall() or []
        followed_ids = set()

        for r in rows:
            followed_ids.add(r["user_id"])
            following.append({
                "user_id": r["user_id"],
                "user_name": f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip()
            })

        cur.execute(
            """
            SELECT user_id, first_name, last_name
            FROM Users
            WHERE user_id <> %s
            ORDER BY first_name ASC, last_name ASC, user_id ASC
            """,
            (current_user_id,)
        )
        all_other_users = cur.fetchall() or []

        for r in all_other_users:
            if r["user_id"] not in followed_ids:
                suggestions.append({
                    "user_id": r["user_id"],
                    "user_name": f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip()
                })

    except Exception as e:
        session["flash_msg"] = f"Error loading follow lists: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return following, suggestions

def _fetch_comments_for_posts(post_ids):
    if not post_ids:
        return {}

    conn = None
    cur = None
    comments_by_post = {}

    try:
        conn = _db_conn()
        cur = conn.cursor(dictionary=True)

        placeholders = ",".join(["%s"] * len(post_ids))
        query = f"""
            SELECT
                sc.comment_id,
                sc.post_id,
                sc.user_id,
                sc.comment_text,
                sc.created_at,
                sc.updated_at,
                u.first_name,
                u.last_name
            FROM Social_Comments sc
            INNER JOIN Users u
                ON sc.user_id = u.user_id
            WHERE sc.post_id IN ({placeholders})
            ORDER BY sc.created_at ASC, sc.comment_id ASC
        """
        cur.execute(query, tuple(post_ids))
        rows = cur.fetchall() or []

        for r in rows:
            post_id = r["post_id"]
            comments_by_post.setdefault(post_id, []).append({
                "comment_id": r["comment_id"],
                "post_id": post_id,
                "user_id": r["user_id"],
                "user_name": f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip(),
                "comment_text": r.get("comment_text") or "",
                "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("created_at") else "",
                "updated_at": r["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("updated_at") else "",
            })

    except Exception as e:
        session["flash_msg"] = f"Error loading comments: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return comments_by_post

def _fetch_tags_for_posts(post_ids):
    if not post_ids:
        return {}

    conn = None
    cur = None
    tags_by_post = {}

    try:
        conn = _db_conn()
        cur = conn.cursor(dictionary=True)

        placeholders = ",".join(["%s"] * len(post_ids))
        query = f"""
            SELECT
                spt.post_id,
                spt.tagged_user_id,
                u.first_name,
                u.last_name
            FROM Social_Post_Tags spt
            INNER JOIN Users u
                ON spt.tagged_user_id = u.user_id
            WHERE spt.post_id IN ({placeholders})
            ORDER BY u.first_name ASC, u.last_name ASC, u.user_id ASC
        """
        cur.execute(query, tuple(post_ids))
        rows = cur.fetchall() or []

        for r in rows:
            post_id = r["post_id"]
            tags_by_post.setdefault(post_id, []).append({
                "user_id": r["tagged_user_id"],
                "user_name": f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip()
            })

    except Exception as e:
        session["flash_msg"] = f"Error loading tags: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return tags_by_post

def _fetch_likes_for_posts(post_ids):
    if not post_ids:
        return {}

    conn = None
    cur = None
    likes_by_post = {}

    try:
        conn = _db_conn()
        cur = conn.cursor(dictionary=True)

        placeholders = ",".join(["%s"] * len(post_ids))
        query = f"""
            SELECT
                spl.post_id,
                spl.user_id,
                u.first_name,
                u.last_name
            FROM Social_Post_Likes spl
            INNER JOIN Users u
                ON spl.user_id = u.user_id
            WHERE spl.post_id IN ({placeholders})
            ORDER BY u.first_name ASC, u.last_name ASC, u.user_id ASC
        """
        cur.execute(query, tuple(post_ids))
        rows = cur.fetchall() or []

        for r in rows:
            post_id = r["post_id"]
            likes_by_post.setdefault(post_id, []).append({
                "user_id": r["user_id"],
                "user_name": f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip()
            })

    except Exception as e:
        session["flash_msg"] = f"Error loading likes: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return likes_by_post

def _fetch_all_posts(current_user_id=None):
    conn = None
    cur = None
    posts = []

    try:
        conn = _db_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
                sp.post_id,
                sp.user_id,
                sp.posts_json,
                sp.location_name,
                sp.image_filename,
                sp.created_at,
                sp.updated_at,
                u.first_name,
                u.last_name
            FROM Social_Posts sp
            INNER JOIN Users u
                ON sp.user_id = u.user_id
            ORDER BY COALESCE(sp.updated_at, sp.created_at) DESC, sp.post_id DESC
            """
        )
        rows = cur.fetchall() or []

        for r in rows:
            versions = _parse_posts_json(r.get("posts_json"))
            image_filename = (r.get("image_filename") or "").strip()

            posts.append({
                "post_id": r["post_id"],
                "user_id": r["user_id"],
                "user_name": f"{(r.get('first_name') or '').strip()} {(r.get('last_name') or '').strip()}".strip(),
                "versions": versions,
                "content": _latest_post_text(versions),
                "location_name": (r.get("location_name") or "").strip(),
                "image_filename": image_filename,
                "image_url": url_for("static", filename=f"social_uploads/{image_filename}") if image_filename else "",
                "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("created_at") else "",
                "updated_at": r["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if r.get("updated_at") else "",
                "comments": [],
                "tags": [],
                "likes": [],
                "liked_by_current_user": False,
            })

        post_ids = [p["post_id"] for p in posts]
        comments_by_post = _fetch_comments_for_posts(post_ids)
        tags_by_post = _fetch_tags_for_posts(post_ids)
        likes_by_post = _fetch_likes_for_posts(post_ids)

        for p in posts:
            p["comments"] = comments_by_post.get(p["post_id"], [])
            p["tags"] = tags_by_post.get(p["post_id"], [])
            p["likes"] = likes_by_post.get(p["post_id"], [])
            if current_user_id is not None:
                p["liked_by_current_user"] = any(l["user_id"] == current_user_id for l in p["likes"])

    except Exception as e:
        session["flash_msg"] = f"Error loading posts: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return posts

@social_bp.route("/", methods=["GET"])
def index():
    if not _require_login():
        return redirect(url_for("auth.login"))

    current_user_id = int(session.get("user_id"))
    first_name = session.get("first_name", "User")
    last_name = session.get("last_name", "")

    food_url = url_for("food.index")
    home_url = url_for("home.home")
    logout_url = url_for("auth.logout")

    posts = _fetch_all_posts(current_user_id=current_user_id)
    all_users = _fetch_all_users()
    following_users, suggested_users = _fetch_following_and_suggestions(current_user_id)

    return render_template_string(
        PAGE_HTML,
        current_user_id=current_user_id,
        first_name=first_name,
        last_name=last_name,
        posts=posts,
        all_users=all_users,
        following_users=following_users,
        suggested_users=suggested_users,
        food_url=food_url,
        home_url=home_url,
        logout_url=logout_url,
    )

@social_bp.route("/follow/<int:followed_user_id>", methods=["POST"])
def follow_user(followed_user_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    follower_user_id = int(session.get("user_id"))

    if follower_user_id == followed_user_id:
        session["flash_msg"] = "You cannot follow yourself."
        return redirect(url_for("social.index"))

    conn = None
    cur = None

    try:
        conn = _db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT IGNORE INTO Social_Follows (follower_user_id, followed_user_id)
            VALUES (%s, %s)
            """,
            (follower_user_id, followed_user_id),
        )
        conn.commit()
        session["flash_msg"] = "User followed."
    except Exception as e:
        session["flash_msg"] = f"Error following user: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return redirect(url_for("social.index"))

@social_bp.route("/unfollow/<int:followed_user_id>", methods=["POST"])
def unfollow_user(followed_user_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    follower_user_id = int(session.get("user_id"))

    conn = None
    cur = None

    try:
        conn = _db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM Social_Follows
            WHERE follower_user_id = %s
              AND followed_user_id = %s
            """,
            (follower_user_id, followed_user_id),
        )
        conn.commit()
        session["flash_msg"] = "User unfollowed."
    except Exception as e:
        session["flash_msg"] = f"Error unfollowing user: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return redirect(url_for("social.index"))

@social_bp.route("/like/<int:post_id>", methods=["POST"])
def like_post(post_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    user_id = int(session.get("user_id"))

    conn = None
    cur = None

    try:
        conn = _db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT IGNORE INTO Social_Post_Likes (post_id, user_id)
            VALUES (%s, %s)
            """,
            (post_id, user_id),
        )
        conn.commit()
        session["flash_msg"] = "Post liked."
    except Exception as e:
        session["flash_msg"] = f"Error liking post: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return redirect(url_for("social.index"))

@social_bp.route("/unlike/<int:post_id>", methods=["POST"])
def unlike_post(post_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    user_id = int(session.get("user_id"))

    conn = None
    cur = None

    try:
        conn = _db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM Social_Post_Likes
            WHERE post_id = %s
              AND user_id = %s
            """,
            (post_id, user_id),
        )
        conn.commit()
        session["flash_msg"] = "Post unliked."
    except Exception as e:
        session["flash_msg"] = f"Error unliking post: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return redirect(url_for("social.index"))

@social_bp.route("/create", methods=["POST"])
def create_post():
    if not _require_login():
        return redirect(url_for("auth.login"))

    raw = (request.form.get("content", "") or "").strip()
    add_location = (request.form.get("add_location", "") == "on")
    enable_tags = (request.form.get("enable_tags", "") == "on")
    location_name = (request.form.get("location_name", "") or "").strip()
    tagged_user_ids = request.form.getlist("tagged_user_ids") if enable_tags else []
    image_file = request.files.get("image")

    if not raw:
        session["flash_msg"] = "Post cannot be empty."
        return redirect(url_for("social.index"))

    if not add_location:
        location_name = ""

    user_id = int(session.get("user_id"))
    posts_json = json.dumps([raw])
    image_filename = _save_uploaded_image(image_file)

    if image_file and getattr(image_file, "filename", "") and not image_filename:
        session["flash_msg"] = "Invalid image file type."
        return redirect(url_for("social.index"))

    conn = None
    cur = None
    tag_cur = None

    try:
        conn = _db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO Social_Posts (user_id, posts_json, location_name, image_filename)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, posts_json, location_name if location_name else None, image_filename),
        )
        post_id = cur.lastrowid

        clean_tag_ids = _clean_tag_ids(tagged_user_ids)

        if clean_tag_ids:
            tag_cur = conn.cursor()
            for tagged_user_id in clean_tag_ids:
                tag_cur.execute(
                    """
                    INSERT INTO Social_Post_Tags (post_id, tagged_user_id, tagged_by_user_id)
                    VALUES (%s, %s, %s)
                    """,
                    (post_id, tagged_user_id, user_id),
                )

        conn.commit()
        session["flash_msg"] = "Post created."
    except Exception as e:
        session["flash_msg"] = f"Error creating post: {e}"
    finally:
        try:
            if tag_cur:
                tag_cur.close()
        except Exception:
            pass
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return redirect(url_for("social.index"))

@social_bp.route("/edit/<int:post_id>", methods=["POST"])
def edit_post(post_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    user_id = int(session.get("user_id"))
    new_content = (request.form.get("content", "") or "").strip()
    add_location = (request.form.get("add_location", "") == "on")
    enable_tags = (request.form.get("enable_tags", "") == "on")
    location_name = (request.form.get("location_name", "") or "").strip()
    tagged_user_ids = request.form.getlist("tagged_user_ids") if enable_tags else []
    image_file = request.files.get("image")

    if not new_content:
        session["flash_msg"] = "Edited post cannot be empty."
        return redirect(url_for("social.index"))

    if not add_location:
        location_name = ""

    conn = None
    cur = None
    cur2 = None
    cur3 = None

    try:
        conn = _db_conn()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT post_id, user_id, posts_json, image_filename
            FROM Social_Posts
            WHERE post_id = %s
            """,
            (post_id,),
        )
        row = cur.fetchone()

        if not row:
            session["flash_msg"] = "Post not found."
            return redirect(url_for("social.index"))

        if int(row["user_id"]) != user_id:
            session["flash_msg"] = "You can only edit your own posts."
            return redirect(url_for("social.index"))

        versions = _parse_posts_json(row.get("posts_json"))
        versions.append(new_content)

        new_image_filename = row.get("image_filename")
        uploaded_name = _save_uploaded_image(image_file)

        if image_file and getattr(image_file, "filename", "") and not uploaded_name:
            session["flash_msg"] = "Invalid image file type."
            return redirect(url_for("social.index"))

        if uploaded_name:
            new_image_filename = uploaded_name

        cur2 = conn.cursor()
        cur2.execute(
            """
            UPDATE Social_Posts
            SET posts_json = %s,
                location_name = %s,
                image_filename = %s
            WHERE post_id = %s
            """,
            (json.dumps(versions), location_name if location_name else None, new_image_filename, post_id),
        )

        cur3 = conn.cursor()
        cur3.execute(
            "DELETE FROM Social_Post_Tags WHERE post_id = %s",
            (post_id,)
        )

        clean_tag_ids = _clean_tag_ids(tagged_user_ids)
        for tagged_user_id in clean_tag_ids:
            cur3.execute(
                """
                INSERT INTO Social_Post_Tags (post_id, tagged_user_id, tagged_by_user_id)
                VALUES (%s, %s, %s)
                """,
                (post_id, tagged_user_id, user_id),
            )

        conn.commit()
        session["flash_msg"] = "Post updated."
    except Exception as e:
        session["flash_msg"] = f"Error editing post: {e}"
    finally:
        try:
            if cur3:
                cur3.close()
        except Exception:
            pass
        try:
            if cur2:
                cur2.close()
        except Exception:
            pass
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return redirect(url_for("social.index"))

@social_bp.route("/comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    comment_text = (request.form.get("comment_text", "") or "").strip()
    if not comment_text:
        session["flash_msg"] = "Comment cannot be empty."
        return redirect(url_for("social.index"))

    user_id = int(session.get("user_id"))

    conn = None
    cur = None
    try:
        conn = _db_conn()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO Social_Comments (post_id, user_id, comment_text)
            VALUES (%s, %s, %s)
            """,
            (post_id, user_id, comment_text),
        )
        conn.commit()
        session["flash_msg"] = "Comment added."
    except Exception as e:
        session["flash_msg"] = f"Error adding comment: {e}"
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return redirect(url_for("social.index"))

@social_bp.route("/edit_comment/<int:comment_id>", methods=["POST"])
def edit_comment(comment_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    user_id = int(session.get("user_id"))
    new_comment_text = (request.form.get("comment_text", "") or "").strip()

    if not new_comment_text:
        session["flash_msg"] = "Edited comment cannot be empty."
        return redirect(url_for("social.index"))

    conn = None
    cur = None
    cur2 = None

    try:
        conn = _db_conn()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT comment_id, user_id
            FROM Social_Comments
            WHERE comment_id = %s
            """,
            (comment_id,),
        )
        row = cur.fetchone()

        if not row:
            session["flash_msg"] = "Comment not found."
            return redirect(url_for("social.index"))

        if int(row["user_id"]) != user_id:
            session["flash_msg"] = "You can only edit your own comments."
            return redirect(url_for("social.index"))

        cur2 = conn.cursor()
        cur2.execute(
            """
            UPDATE Social_Comments
            SET comment_text = %s
            WHERE comment_id = %s
            """,
            (new_comment_text, comment_id),
        )
        conn.commit()
        session["flash_msg"] = "Comment updated."
    except Exception as e:
        session["flash_msg"] = f"Error editing comment: {e}"
    finally:
        try:
            if cur2:
                cur2.close()
        except Exception:
            pass
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    return redirect(url_for("social.index"))

PAGE_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <title>NutriLog | Social Media</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='styles.css') }}">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    .page-wrap {
      max-width: 1280px;
      margin: 0 auto;
      padding: 18px;
    }

    .main-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 20px;
      align-items: start;
    }

    .main-column {
      min-width: 0;
    }

    .sidebar-column {
      position: sticky;
      top: 18px;
    }

    .card {
      border: 1px solid #ddd;
      border-radius: 12px;
      padding: 16px;
      margin: 16px auto;
      background: #fff;
      width: 100%;
      box-sizing: border-box;
    }

    .sidebar-card {
      border: 1px solid #ddd;
      border-radius: 12px;
      padding: 16px;
      background: #fff;
      width: 100%;
      box-sizing: border-box;
      margin-bottom: 16px;
    }

    .banner {
      max-width: 1280px;
      margin: 20px auto 0 auto;
      padding: 18px 22px;
      border: 1px solid #ddd;
      border-radius: 14px;
      background: #fff;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      box-sizing: border-box;
    }

    .banner-title {
      font-size: 28px;
      font-weight: 800;
      margin: 0;
    }

    .banner-user {
      font-size: 16px;
      color: #444;
      font-weight: 600;
    }

    textarea, input[type="text"], input[type="file"] {
      width: 100%;
      padding: 12px;
      border: 1px solid #ddd;
      border-radius: 10px;
      box-sizing: border-box;
    }

    textarea {
      min-height: 100px;
      resize: vertical;
    }

    .comment-form textarea {
      min-height: 70px;
    }

    .post-actions {
      margin-top: 10px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }

    .post-card {
      border: 1px solid #e6e6e6;
      border-radius: 14px;
      padding: 16px;
      margin-bottom: 14px;
      background: #fff;
    }

    .post-user {
      font-weight: 800;
      margin-bottom: 8px;
    }

    .post-content {
      white-space: pre-wrap;
      line-height: 1.5;
      margin-bottom: 12px;
    }

    .post-image {
      max-width: 100%;
      max-height: 420px;
      display: block;
      margin: 12px 0;
      border-radius: 12px;
      border: 1px solid #ddd;
      object-fit: contain;
      background: #fafafa;
    }

    .muted {
      color: #666;
      font-size: 13px;
    }

    .edit-box {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #eee;
      display: none;
    }

    .comment-section {
      margin-top: 16px;
      padding-top: 14px;
      border-top: 1px solid #eee;
    }

    .comment-item {
      border: 1px solid #eee;
      border-radius: 10px;
      padding: 10px;
      background: #fafafa;
      margin-top: 10px;
    }

    .comment-user {
      font-weight: 700;
      margin-bottom: 6px;
    }

    .field-row {
      margin-top: 12px;
    }

    .tag-list {
      margin: 8px 0 10px 0;
      font-size: 14px;
      color: #333;
      font-weight: 600;
    }

    .location-line {
      margin: 8px 0 10px 0;
      font-size: 14px;
      color: #333;
      font-weight: 600;
    }

    .likes-line {
      margin: 8px 0 10px 0;
      font-size: 14px;
      color: #333;
      font-weight: 600;
    }

    .tag-suggestions {
      margin-top: 8px;
      border: 1px solid #ddd;
      border-radius: 10px;
      background: #fff;
      overflow: hidden;
    }

    .tag-suggestion-item {
      padding: 10px 12px;
      border-bottom: 1px solid #eee;
      cursor: pointer;
    }

    .tag-suggestion-item:last-child {
      border-bottom: none;
    }

    .tag-suggestion-item:hover {
      background: #f5f5f5;
    }

    .selected-tags {
      margin-top: 10px;
    }

    .selected-tag-chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border: 1px solid #ddd;
      border-radius: 999px;
      background: #f7f7f7;
      margin-right: 8px;
      margin-top: 8px;
      font-size: 13px;
    }

    .selected-tag-chip button {
      border: none;
      background: transparent;
      cursor: pointer;
      font-weight: 700;
      font-size: 14px;
    }

    .follow-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-top: 12px;
    }

    .follow-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 10px;
      border: 1px solid #eee;
      border-radius: 10px;
      background: #fafafa;
    }

    .follow-name {
      font-weight: 600;
      line-height: 1.3;
    }

    .follow-form {
      margin: 0;
    }

    .sidebar-title {
      margin: 0 0 10px 0;
      font-size: 18px;
      font-weight: 800;
    }

    .comment-edit-box {
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid #eee;
      display: none;
    }

    @media (max-width: 980px) {
      .main-grid {
        grid-template-columns: 1fr;
      }

      .sidebar-column {
        position: static;
      }
    }
  </style>

  <script>
    const ALL_USERS = {{ all_users|tojson }};

    function toggleCommentEdit(commentId) {
      const box = document.getElementById("edit-comment-box-" + commentId);
      if (!box) return;
      box.style.display = (box.style.display === "block") ? "none" : "block";
    }

    function toggleEdit(postId) {
      const box = document.getElementById("edit-box-" + postId);
      if (!box) return;
      box.style.display = (box.style.display === "block") ? "none" : "block";
    }

    function toggleLocationInput(boxId, checked) {
      const box = document.getElementById(boxId);
      if (!box) return;
      box.style.display = checked ? "block" : "none";
    }

    function toggleTagBox(boxId, checked) {
      const box = document.getElementById(boxId);
      if (!box) return;
      box.style.display = checked ? "block" : "none";
    }

    function getSelectedIds(containerId) {
      const container = document.getElementById(containerId);
      if (!container) return [];
      const hiddenInputs = container.querySelectorAll('input[name="tagged_user_ids"]');
      return Array.from(hiddenInputs).map(x => Number(x.value));
    }

    function showTagSuggestions(inputId, suggestionsId, selectedContainerId) {
      const input = document.getElementById(inputId);
      const suggestions = document.getElementById(suggestionsId);
      if (!input || !suggestions) return;

      const q = input.value.trim().toLowerCase();
      suggestions.innerHTML = "";

      if (!q) return;

      const selectedIds = getSelectedIds(selectedContainerId);

      const matches = ALL_USERS
        .filter(u =>
          !selectedIds.includes(Number(u.user_id)) &&
          u.user_name.toLowerCase().includes(q)
        )
        .slice(0, 5);

      for (const user of matches) {
        const div = document.createElement("div");
        div.className = "tag-suggestion-item";
        div.textContent = user.user_name;
        div.onclick = function () {
          addTaggedUser(selectedContainerId, user.user_id, user.user_name);
          input.value = "";
          suggestions.innerHTML = "";
        };
        suggestions.appendChild(div);
      }
    }

    function addTaggedUser(containerId, userId, userName) {
      const container = document.getElementById(containerId);
      if (!container) return;

      const existing = container.querySelector(`input[name="tagged_user_ids"][value="${userId}"]`);
      if (existing) return;

      const chip = document.createElement("span");
      chip.className = "selected-tag-chip";
      chip.setAttribute("data-user-id", userId);

      const label = document.createElement("span");
      label.textContent = "@" + userName;

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.textContent = "×";
      removeBtn.onclick = function () {
        chip.remove();
      };

      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "tagged_user_ids";
      hidden.value = userId;

      chip.appendChild(label);
      chip.appendChild(removeBtn);
      chip.appendChild(hidden);

      container.appendChild(chip);
    }

    function preloadTags(containerId, tags) {
      if (!Array.isArray(tags)) return;
      for (const tag of tags) {
        addTaggedUser(containerId, tag.user_id, tag.user_name);
      }
    }
  </script>
</head>
<body>
  <nav class="navbar">
    <div class="logo">
      <img src="{{ url_for('static', filename='nutrilog_icon.png') }}" alt="NutriLog">
      <span>NutriLog</span>
    </div>

    <ul class="menu">
      <li>
        <form action="{{ home_url }}" method="get">
          <button type="submit" class="nav-btn">Home</button>
        </form>
      </li>
      <li>
        <form action="{{ food_url }}" method="get">
          <button type="submit" class="nav-btn">Add Food</button>
        </form>
      </li>
      <li>
        <form action="{{ logout_url }}" method="post">
          <button type="submit" class="nav-btn">Logout</button>
        </form>
      </li>
    </ul>
  </nav>

  <div class="banner">
    <div class="banner-title">Social Media</div>
    <div class="banner-user">
      Logged in as: {{ first_name }} {{ last_name }}
    </div>
  </div>

  <div class="page-wrap">
    {% if session.get("flash_msg") %}
      <div class="card">
        <div class="muted">{{ session.get("flash_msg") }}</div>
      </div>
      {% set _ = session.pop("flash_msg") %}
    {% endif %}

    <div class="main-grid">
      <div class="main-column">
        <div class="card">
          <h2>Create Post</h2>
          <form method="post" action="{{ url_for('social.create_post') }}" enctype="multipart/form-data">
            <textarea name="content" placeholder="Write something..."></textarea>

            <div class="field-row">
              <label>
                <input type="checkbox" name="add_location" onchange="toggleLocationInput('create-location-box', this.checked)">
                Add location
              </label>
            </div>

            <div class="field-row" id="create-location-box" style="display:none;">
              <input type="text" name="location_name" placeholder="Type a location name">
            </div>

            <div class="field-row">
              <label>
                <input type="checkbox" name="enable_tags" onchange="toggleTagBox('create-tag-box', this.checked)">
                Tag users
              </label>
            </div>

            <div class="field-row" id="create-tag-box" style="display:none;">
              <input
                type="text"
                id="tag-search-create"
                placeholder="Type a name to tag"
                autocomplete="off"
                oninput="showTagSuggestions('tag-search-create', 'tag-suggestions-create', 'selected-tags-create')"
              >
              <div id="tag-suggestions-create" class="tag-suggestions"></div>
              <div id="selected-tags-create" class="selected-tags"></div>
              <div class="muted">Start typing and click a suggestion.</div>
            </div>

            <div class="field-row">
              <label><b>Upload image</b></label>
              <input type="file" name="image" accept=".jpg,.jpeg,.png,.webp,.gif,.bmp,image/*">
            </div>

            <div class="post-actions">
              <button type="submit" class="nav-btn">Post</button>
            </div>
          </form>
        </div>

        <div class="card">
          <h2>Recent Posts</h2>

          {% if posts %}
            {% for post in posts %}
              <div class="post-card">
                <div class="post-user"><b>{{ post.user_name }}</b></div>

                {% if post.location_name %}
                  <div class="location-line">Location: {{ post.location_name }}</div>
                {% endif %}

                {% if post.tags %}
                  <div class="tag-list">
                    With:
                    {% for tag in post.tags %}
                      {{ tag.user_name }}{% if not loop.last %}, {% endif %}
                    {% endfor %}
                  </div>
                {% endif %}

                <div class="post-content">{{ post.content }}</div>

                {% if post.image_url %}
                  <img src="{{ post.image_url }}" alt="Post image" class="post-image">
                {% endif %}

                <div class="muted">
                  Created: {{ post.created_at }} |
                  Updated: {{ post.updated_at }}
                </div>

                <div class="post-actions">
                  {% if post.liked_by_current_user %}
                    <form method="post" action="{{ url_for('social.unlike_post', post_id=post.post_id) }}">
                      <button type="submit" class="nav-btn">Unlike</button>
                    </form>
                  {% else %}
                    <form method="post" action="{{ url_for('social.like_post', post_id=post.post_id) }}">
                      <button type="submit" class="nav-btn">Like</button>
                    </form>
                  {% endif %}

                  {% if post.user_id == current_user_id %}
                    <button type="button" class="nav-btn" onclick="toggleEdit({{ post.post_id }})">Edit</button>
                  {% endif %}
                </div>

                {% if post.likes %}
                  <div class="likes-line">
                    Liked by:
                    {% for like in post.likes %}
                      {{ like.user_name }}{% if not loop.last %}, {% endif %}
                    {% endfor %}
                  </div>
                {% else %}
                  <div class="likes-line">Liked by: nobody yet</div>
                {% endif %}

                {% if post.user_id == current_user_id %}
                  <div class="edit-box" id="edit-box-{{ post.post_id }}">
                    <form method="post" action="{{ url_for('social.edit_post', post_id=post.post_id) }}" enctype="multipart/form-data">
                      <textarea name="content">{{ post.content }}</textarea>

                      <div class="field-row">
                        <label>
                          <input
                            type="checkbox"
                            name="add_location"
                            onchange="toggleLocationInput('edit-location-box-{{ post.post_id }}', this.checked)"
                            {% if post.location_name %}checked{% endif %}
                          >
                          Add location
                        </label>
                      </div>

                      <div
                        class="field-row"
                        id="edit-location-box-{{ post.post_id }}"
                        style="display:{% if post.location_name %}block{% else %}none{% endif %};"
                      >
                        <input type="text" name="location_name" value="{{ post.location_name }}" placeholder="Type a location name">
                      </div>

                      <div class="field-row">
                        <label>
                          <input
                            type="checkbox"
                            name="enable_tags"
                            onchange="toggleTagBox('edit-tag-box-{{ post.post_id }}', this.checked)"
                            {% if post.tags %}checked{% endif %}
                          >
                          Tag users
                        </label>
                      </div>

                      <div
                        class="field-row"
                        id="edit-tag-box-{{ post.post_id }}"
                        style="display:{% if post.tags %}block{% else %}none{% endif %};"
                      >
                        <input
                          type="text"
                          id="tag-search-edit-{{ post.post_id }}"
                          placeholder="Type a name to tag"
                          autocomplete="off"
                          oninput="showTagSuggestions('tag-search-edit-{{ post.post_id }}', 'tag-suggestions-edit-{{ post.post_id }}', 'selected-tags-edit-{{ post.post_id }}')"
                        >
                        <div id="tag-suggestions-edit-{{ post.post_id }}" class="tag-suggestions"></div>
                        <div id="selected-tags-edit-{{ post.post_id }}" class="selected-tags"></div>
                        <div class="muted">Start typing and click a suggestion.</div>
                      </div>

                      <div class="field-row">
                        <label><b>Replace image</b></label>
                        <input type="file" name="image" accept=".jpg,.jpeg,.png,.webp,.gif,.bmp,image/*">
                      </div>

                      <div class="post-actions">
                        <button type="submit" class="nav-btn">Save Edit</button>
                      </div>
                    </form>
                  </div>

                  <script>
                    preloadTags("selected-tags-edit-{{ post.post_id }}", {{ post.tags|tojson }});
                  </script>
                {% endif %}

                <div class="comment-section">
                  <h4>Comments</h4>

                  {% if post.comments %}
                    {% for comment in post.comments %}
                      <div class="comment-item">
                        <div class="comment-user"><b>{{ comment.user_name }}</b></div>
                        <div class="post-content">{{ comment.comment_text }}</div>
                        <div class="muted">{{ comment.created_at }}</div>

                        {% if comment.user_id == current_user_id %}
                          <div class="post-actions">
                            <button
                              type="button"
                              class="nav-btn"
                              onclick="toggleCommentEdit({{ comment.comment_id }})"
                            >
                              Edit Comment
                            </button>
                          </div>

                          <div class="comment-edit-box" id="edit-comment-box-{{ comment.comment_id }}">
                            <form method="post" action="{{ url_for('social.edit_comment', comment_id=comment.comment_id) }}">
                              <textarea name="comment_text">{{ comment.comment_text }}</textarea>
                              <div class="post-actions">
                                <button type="submit" class="nav-btn">Save Comment</button>
                              </div>
                            </form>
                          </div>
                        {% endif %}
                      </div>
                    {% endfor %}
                  {% else %}
                    <p class="muted">No comments yet.</p>
                  {% endif %}

                  <form method="post" class="comment-form" action="{{ url_for('social.add_comment', post_id=post.post_id) }}">
                    <textarea name="comment_text" placeholder="Write a comment..."></textarea>
                    <div class="post-actions">
                      <button type="submit" class="nav-btn">Comment</button>
                    </div>
                  </form>
                </div>
              </div>
            {% endfor %}
          {% else %}
            <p class="muted">No posts yet.</p>
          {% endif %}
        </div>
      </div>

      <div class="sidebar-column">
        <div class="sidebar-card">
          <h3 class="sidebar-title">Following</h3>
          {% if following_users %}
            <div class="follow-list">
              {% for user in following_users %}
                <div class="follow-item">
                  <div class="follow-name">{{ user.user_name }}</div>
                  <form class="follow-form" method="post" action="{{ url_for('social.unfollow_user', followed_user_id=user.user_id) }}">
                    <button type="submit" class="nav-btn">Unfollow</button>
                  </form>
                </div>
              {% endfor %}
            </div>
          {% else %}
            <p class="muted">You are not following anyone yet.</p>
          {% endif %}
        </div>

        <div class="sidebar-card">
          <h3 class="sidebar-title">Suggested Users</h3>
          {% if suggested_users %}
            <div class="follow-list">
              {% for user in suggested_users %}
                <div class="follow-item">
                  <div class="follow-name">{{ user.user_name }}</div>
                  <form class="follow-form" method="post" action="{{ url_for('social.follow_user', followed_user_id=user.user_id) }}">
                    <button type="submit" class="nav-btn">Follow</button>
                  </form>
                </div>
              {% endfor %}
            </div>
          {% else %}
            <p class="muted">No suggested users right now.</p>
          {% endif %}
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""
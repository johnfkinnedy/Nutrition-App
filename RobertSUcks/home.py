from flask import Blueprint, session, redirect, url_for, render_template_string

home_bp = Blueprint("home", __name__, url_prefix="/home")

@home_bp.route("/")
def home():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))

    user_id = session.get("user_id")
    first_name = session.get("first_name", "User")
    last_name = session.get("last_name", "")

    logout_url = url_for("auth.logout")
    maps_url = url_for("maps.index")
    food_url = url_for("food.index")
    clock_url = url_for("clock.index")

    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>NutriLog | Dashboard</title>
        <link rel="stylesheet" href="{{ url_for('static', filename='styles.css') }}">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body>
        <nav class="navbar">
    <div class="logo">
        <img src="{{ url_for('static', filename='nutrilog_icon.png') }}" alt="NutriLog">
        <span>NutriLog</span>
    </div>

    <ul class="menu">
        <li>
            <form action="{{ maps_url }}" method="get">
                <button type="submit" class="nav-btn">Maps</button>
            </form>
        </li>

        <li>
            <form action="{{ food_url }}" method="get">
                <button type="submit" class="nav-btn">Add Food</button>
            </form>
        </li>

        <li>
            <form action="{{ clock_url }}" method="get">
                <button type="submit" class="nav-btn">Clock In/Out</button>
            </form>
        </li>

        <li>
            <form action="{{ logout_url }}" method="post">
                <button type="submit" class="nav-btn">Logout</button>
            </form>
        </li>
    </ul>
</nav>
        <header class="hero">
            <h1>Welcome back, {{ first_name }}!</h1>
            <p>Your personalized nutrition dashboard</p>
        </header>

        <main class="container">
            <div class="card">
                <h2>Dashboard Overview</h2>
                <p>You are logged in as:</p>
                <div class="user-badge">
                    <strong>User ID:</strong> {{ user_id }}<br>
                    <strong>Name:</strong> {{ first_name }} {{ last_name }}
                </div>
            </div>
        </main>

    </body>
    </html>
    """,
    user_id=user_id,
    first_name=first_name,
    last_name=last_name,
    logout_url=logout_url,
    maps_url=maps_url,
    food_url=food_url,
    clock_url=clock_url
    )
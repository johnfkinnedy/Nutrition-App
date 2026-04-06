from flask import Flask, redirect, url_for
from login_home import auth_bp
from home import home_bp
from food_ml import food_bp
from social_media import social_bp

app = Flask(__name__)
app.secret_key = "dev"

app.register_blueprint(auth_bp)
app.register_blueprint(home_bp)
app.register_blueprint(food_bp)
app.register_blueprint(social_bp)

@app.route("/")
def index():
    return redirect(url_for("auth.login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
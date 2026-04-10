import os
from flask import Flask
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY"),
)


@app.route("/")
def index():
    return "coach-saas is running"


if __name__ == "__main__":
    app.run(debug=True)

import subprocess
import sys
import time
import os
from Backend.models import User
from Backend.security import hash_password

def run_project():
    # Caminho absoluto da raiz do projeto (onde o run.py está)
    base_path = os.path.dirname(os.path.abspath(__file__))
    
    print("NOC Lite...")
    backend_cmd = [
        sys.executable, "-m", "uvicorn", 
        "Backend.main:app",
        "--port", "8000", 
        "--reload"
    ]
    frontend_cmd = [
        sys.executable, "-m", "http.server", "3000", 
        "--directory", "Frontend"
    ]

    try:
        pasta_back = subprocess.Popen(backend_cmd, cwd=base_path)
        pasta_front = subprocess.Popen(frontend_cmd, cwd=base_path)

        print(f"API: http://127.0.0.1:8000")
        print(f"Site: http://127.0.0.1:3000")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nDesligando o sistema...")
        pasta_back.terminate()
        pasta_front.terminate()
        print("Desligado.")

if __name__ == "__main__":
    run_project()

def create_default_admin(db):
    admin = db.query(User).filter(User.username == "admin").first()

    if not admin:
        new_admin = User(
            username="admin",
            password_hash=hash_password("admin"),
            must_change_password=True
        )
        db.add(new_admin)
        db.commit()

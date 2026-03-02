from Backend.database import SessionLocal
from Backend.models import User
from Backend.security import hash_password

db = SessionLocal()
# Verifica se o usuário já existe
if not db.query(User).filter(User.username == "admin").first():
    novo_user = User(
        username="admin",
        password_hash=hash_password("admin"), # Altere sua senha aqui
        must_change_password=True
    )
    db.add(novo_user)
    db.commit()
    print("Usuário admin criado com sucesso!")
db.close()
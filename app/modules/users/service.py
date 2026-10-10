from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.core.security import hash_password
from app.modules.audit import service as audit
from app.modules.users.models import User

USER_FIELDS = ("email", "full_name", "role", "is_active")


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_stmt(self):
        return select(User).order_by(User.id)

    def create_user(self, data: dict, actor) -> User:
        if self.db.scalars(select(User).where(func.lower(User.email) == data["email"])).first():
            raise ConflictError("email_taken", f"Email {data['email']} is already used")
        user = User(email=data["email"], full_name=data.get("full_name", ""), role=data["role"],
                    password_hash=hash_password(data["password"]), is_active=True)
        self.db.add(user)
        self.db.flush()
        audit.record(self.db, actor, "create", "user", user.uuid, after=audit.snapshot(user, USER_FIELDS))
        self.db.commit()
        self.db.refresh(user)
        return user

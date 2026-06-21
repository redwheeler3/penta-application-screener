from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db


def require_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Authentication required.")

    return user


# Note: there is intentionally no role gate here. Every committee member is a
# trusted screener, so all routes use require_current_user. Re-add a
# require_admin dependency if a genuinely admin-only surface ever appears.


from models import db, Transaction, User

def save_customer_id(customer_id, c_id):
    user = db.session.execute(db.select(User).filter_by(email=customer_id)).scalar_one_or_none()
    user.payment_customer_id = c_id
    db.session.commit()

def get_customer_id(email):
    user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    if user:
        return user.payment_customer_id
    

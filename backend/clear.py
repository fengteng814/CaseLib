from database import SessionLocal
import models

db = SessionLocal()
db.query(models.Image).delete()
db.commit()
db.close()
print("images 表已清空")

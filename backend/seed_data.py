"""
简单示例数据写入脚本。

在 backend 目录下运行：

    python seed_data.py

执行前请确认已经用 app.py 创建过数据库（或先跑一次服务）。
"""

from sqlalchemy.orm import Session

import models
from database import SessionLocal


def main():
    db: Session = SessionLocal()
    try:
        # 如果已经有项目，就不重复插入
        existing = db.query(models.Project).count()
        if existing > 0:
            print("数据库中已存在项目，跳过示例数据插入。")
            return

        p1 = models.Project(
            name="宜宾高铁南区体育中心",
            location="宜宾",
            year=2023,
            description="山影浮舟的大屋顶体育综合体。",
            tags="体育,大屋顶,清水混凝土",
        )
        p2 = models.Project(
            name="某乡村会客厅",
            location="安徽",
            year=2022,
            description="围绕竹林与水院展开的乡村更新项目。",
            tags="乡村,更新,会客厅,庭院",
        )

        db.add_all([p1, p2])
        db.flush()  # 先拿到 id

        img1 = models.Image(
            project_id=p1.id,
            title="主馆夜景",
            image_path="images/yibin_main_night.jpg",
            thumb_path="thumbs/yibin_main_night.jpg",
            tags="夜景,大屋顶,灯光",
        )
        img2 = models.Image(
            project_id=p1.id,
            title="看台内景",
            image_path="images/yibin_stand_interior.jpg",
            thumb_path="thumbs/yibin_stand_interior.jpg",
            tags="看台,观众厅,室内",
        )
        img3 = models.Image(
            project_id=p2.id,
            title="竹林院落",
            image_path="images/courtyard_bamboo.jpg",
            thumb_path="thumbs/courtyard_bamboo.jpg",
            tags="竹林,院落,乡村",
        )

        db.add_all([img1, img2, img3])
        db.flush()

        # 设置封面图
        p1.cover_image_id = img1.id
        p2.cover_image_id = img3.id

        db.commit()
        print("示例数据插入完成。请在 media/images 和 media/thumbs 中放入对应文件名的图片。")
    finally:
        db.close()


if __name__ == "__main__":
    main()

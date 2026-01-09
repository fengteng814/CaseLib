# database.py
from pathlib import Path
import configparser
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 读取 config.ini 获取数据库路径
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

# 从 config.ini 中读取数据库路径
db_path_from_config = config.get("paths", "db_path", fallback="db/cases.sqlite")

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / db_path_from_config
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# 创建 SQLite 引擎
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 单线程限制
)

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 所有模型继承的基类
Base = declarative_base()

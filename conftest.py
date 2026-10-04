import os
import tempfile

# 测试使用独立的临时数据库与上传目录，且不注入演示工单
_tmp = tempfile.mkdtemp(prefix="glass_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("UPLOAD_DIR", f"{_tmp}/uploads")
os.environ.setdefault("GLASS_SEED_DEMO", "0")

# 汽车玻璃保险直赔与安装验收系统

玻璃门店从**接车报价 → 保险方案 → 库存确认 → 安装施工 → 固化验收 → 交车**全程在同一张工单中办理；
车主可在线查看玻璃型号、保险承担、自付金额与预计提车时间。

## 一条命令启动

```bash
./run.sh
```

首次运行自动安装依赖、初始化 SQLite 与演示工单，随后启动服务：

- 门店工作台 / 车主查询：<http://localhost:8000/>
- 接口文档（Swagger）：<http://localhost:8000/docs>
- 演示工单：`WO20261004001`（车主 张伟，报案号 `CLM-DEMO-001`，可用手机号 `13800001234` 在车主端查询）

技术栈：Python + FastAPI + SQLAlchemy 2 + SQLite，前端 Vue 3（本地 vendor，无需 npm 构建），
安装照片保存在本地 `uploads/`，数据库文件在 `data/glassshop.db`。

## 核心业务规则（均由服务端强制，前端仅作引导）

1. **安排施工三前提**：门店已确认库存 + 车主已确认报价 + 保险方案已通过，缺一返回 409。
2. **施工暂停**：发现型号不符或新破损必须暂停，重新出具变更报价，车主**重新授权**后方可复工。
3. **交车门禁（四重硬性条件）**：
   - 胶固化截止时间已到（登记固化所需分钟数，系统计算截止时刻）；
   - 安装验收合格（不合格须整改复检）；
   - 至少一张安装照片；
   - 当前报价已由车主授权确认。
   任一不满足，按钮禁用且服务端 `POST /deliver` 同样 409 拒绝——**未固化车辆不能提前交付**。
4. **拒赔转自费**：保险拒赔后生成全新自费报价（保险承担 0），原保险报价保留为历史版本；
   须车主对新报价**重新授权确认**，旧版本不可再确认。
5. **迟到理赔回执不覆盖**：回执按「签发时间」与「车主确认时间」比较——
   车主已确认自费/变更方案后，迟到的保险回执只入库留痕（`applied=false` 并记录原因），
   不修改报价金额、不改变工单执行的方案。
6. **全程可追溯**：报价多版本、每次授权语句、回执到店/签发时间、照片、验收结论、交车经办人全部留档。

## 主要接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/orders` | 接车开单（自动生成工单号，首张报价随后出具） |
| POST | `/api/orders/{id}/quotes` | 初次报价；仅暂停中可出施工变更报价 |
| POST | `/api/orders/{id}/convert-self-pay` | 拒赔转自费新报价（原版保留） |
| POST | `/api/orders/{id}/quotes/{v}/confirm` | 车主授权确认（必须填写授权语） |
| POST | `/api/orders/{id}/stock` · `/schedule` | 库存确认 · 安排施工 |
| POST | `/api/orders/{id}/install/start\|pause\|resume\|finish` | 施工流转 |
| POST | `/api/orders/{id}/photos` | 上传安装照片（本地存储） |
| POST | `/api/orders/{id}/cure` | 登记胶固化分钟数 → 固化截止时间 |
| POST | `/api/orders/{id}/inspect` | 提交验收结果 |
| GET  | `/api/orders/{id}/delivery-gate` | 实时交车放行判定（含剩余固化分钟） |
| POST | `/api/orders/{id}/deliver` | 交车（服务端强制门禁） |
| POST | `/api/sim/insurance/receipt` | **模拟保险接口**：按报案号推送回执，`issued_minutes_ago` 可模拟迟到 |

## 验证

```bash
python3 e2e_test.py     # 33 项端到端规则断言（需先 ./run.sh；含 1 分钟固化等待）
```

覆盖：施工三前提、暂停-变更-重新授权-复工、无照片/未固化/验收未过禁交车、拒赔转自费重新授权、
迟到回执不覆盖已确认方案、固化到期后放行与重复交车拦截。

## 目录结构

```
backend/        FastAPI 应用（main 路由 / models 模型 / services 业务规则 / schemas / seed 演示数据）
static/         Vue 3 单页应用（app.js / styles.css / vendor/vue）
uploads/        安装照片本地存储
data/           SQLite 数据库
run.sh          一条命令启动
e2e_test.py     端到端业务规则验证
```

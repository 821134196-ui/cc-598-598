/* 汽车玻璃保险直赔与安装验收系统 —— Vue 3 前端（无构建，global build） */
const { createApp } = Vue;

const STATUS_LABELS = {
  created: "报价中",
  ready: "待施工",
  scheduled: "已排程",
  installing: "施工中",
  paused: "已暂停",
  installed: "待交车",
  delivered: "已交车",
};
const STATUS_CLASS = {
  created: "gray", ready: "blue", scheduled: "blue",
  installing: "orange", paused: "red", installed: "orange", delivered: "green",
};
const QUOTE_KIND_LABELS = { insurance: "保险直赔", self_pay: "拒赔转自费", rework: "施工变更" };
const QUOTE_STATUS_LABELS = {
  draft: "草稿", pending_customer: "待车主确认", confirmed: "车主已确认", superseded: "已作废/被取代",
};
const INS_LABELS = { pending: "等待回执", approved: "已赔付", rejected: "已拒赔" };
const STEPS = [
  ["created", "接车报价"], ["ready", "方案/库存就绪"], ["scheduled", "安排施工"],
  ["installing", "安装施工"], ["installed", "固化与验收"], ["delivered", "交车"],
];

const fmtMoney = (n) => "¥" + (Number(n || 0)).toFixed(2);
const fmtTime = (s) => !s ? "—" : String(s).replace("T", " ").slice(0, 16);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || `请求失败 (${res.status})`;
    throw new Error(Array.isArray(detail) ? JSON.stringify(detail) : detail);
  }
  return data;
}

/* ============================================================ 工单列表 */
const OrderList = {
  props: ["view"],
  data() {
    return {
      orders: [], loading: false, error: "",
      status: "", phone: "", plate: "",
    };
  },
  created() { this.load(); },
  methods: {
    STATUS_LABELS, STATUS_CLASS, fmtMoney, fmtTime,
    async load() {
      this.loading = true; this.error = "";
      try {
        const p = new URLSearchParams();
        if (this.status) p.set("status", this.status);
        if (this.phone) p.set("phone", this.phone);
        if (this.plate) p.set("plate", this.plate);
        this.orders = await api("/api/orders?" + p.toString());
      } catch (e) { this.error = e.message; } finally { this.loading = false; }
    },
    open(o) { this.$emit("open", o.id); },
  },
  template: `
  <div>
    <div class="card">
      <h2>工单列表 <span class="sub">门店工作台</span></h2>
      <div class="btn-row" style="margin-bottom:12px">
        <select v-model="status">
          <option value="">全部状态</option>
          <option v-for="(label,k) in STATUS_LABELS" :key="k" :value="k">{{ label }}</option>
        </select>
        <input v-model="phone" placeholder="车主手机号" style="width:160px" />
        <input v-model="plate" placeholder="车牌" style="width:140px" />
        <button class="btn secondary" @click="load">查询</button>
        <button class="btn" @click="$emit('new')">+ 接车开单</button>
      </div>
      <div v-if="error" class="alert error">{{ error }}</div>
      <table>
        <thead><tr>
          <th>工单号</th><th>车牌/车型</th><th>车主</th><th>玻璃</th>
          <th>当前报价</th><th>保险</th><th>自付</th><th>状态</th><th>创建</th>
        </tr></thead>
        <tbody>
          <tr v-for="o in orders" :key="o.id" class="clickable" @click="open(o)">
            <td>{{ o.order_no }}</td>
            <td>{{ o.plate_no }}<div class="muted small">{{ o.car_model }}</div></td>
            <td>{{ o.customer_name }}</td>
            <td>{{ o.glass_position }}<div class="muted small">{{ o.current_glass_model || '未定型号' }}</div></td>
            <td class="money">{{ fmtMoney(o.current_total) }}</td>
            <td><span class="badge" :class="o.insurance_decision==='approved'?'green':o.insurance_decision==='rejected'?'red':'gray'">{{ INS_LABELS[o.insurance_decision] }}</span></td>
            <td class="money self">{{ fmtMoney(o.current_self_pay) }}</td>
            <td><span class="badge" :class="STATUS_CLASS[o.status]">{{ STATUS_LABELS[o.status] }}</span></td>
            <td class="muted small">{{ fmtTime(o.created_at) }}</td>
          </tr>
          <tr v-if="!orders.length"><td colspan="9" class="muted" style="text-align:center;padding:24px">暂无工单，点击“接车开单”开始</td></tr>
        </tbody>
      </table>
    </div>
  </div>`,
};

/* ============================================================ 新建工单 */
const NewOrder = {
  emits: ["created", "cancel"],
  data() {
    return {
      form: { customer_name: "", customer_phone: "", plate_no: "", car_model: "",
              glass_position: "前挡风玻璃", note: "", insurance_company: "", claim_no: "" },
      error: "", busy: false,
    };
  },
  methods: {
    async submit() {
      this.busy = true; this.error = "";
      try {
        const o = await api("/api/orders", { method: "POST", body: JSON.stringify(this.form) });
        this.$emit("created", o.id);
      } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
  },
  template: `
  <div class="card" style="max-width:680px">
    <h2>接车开单</h2>
    <div v-if="error" class="alert error">{{ error }}</div>
    <div class="grid cols-2">
      <div class="field"><label>车主姓名 *</label><input v-model="form.customer_name" /></div>
      <div class="field"><label>手机号 *</label><input v-model="form.customer_phone" /></div>
      <div class="field"><label>车牌号 *</label><input v-model="form.plate_no" /></div>
      <div class="field"><label>车型 *</label><input v-model="form.car_model" /></div>
      <div class="field"><label>玻璃部位 *</label>
        <select v-model="form.glass_position">
          <option>前挡风玻璃</option><option>后挡风玻璃</option>
          <option>左前门玻璃</option><option>右前门玻璃</option>
          <option>左后门玻璃</option><option>右后门玻璃</option><option>天窗玻璃</option>
        </select>
      </div>
      <div class="field"><label>保险公司（可空）</label><input v-model="form.insurance_company" placeholder="如：平安财险" /></div>
      <div class="field"><label>报案号（可空）</label><input v-model="form.claim_no" placeholder="如：CLM-2026-0001" /></div>
      <div class="field" style="grid-column:1/-1"><label>接车检查备注</label><textarea v-model="form.note" rows="2"></textarea></div>
    </div>
    <div class="btn-row" style="margin-top:14px">
      <button class="btn" :disabled="busy" @click="submit">创建工单并报价</button>
      <button class="btn secondary" @click="$emit('cancel')">取消</button>
    </div>
  </div>`,
};

/* ============================================================ 报价卡片/表单 */
const QuoteSection = {
  props: ["order"],
  emits: ["changed"],
  data() {
    return {
      showForm: false,
      form: this.blankForm(),
      showSelfPay: false,
      sp: this.blankForm(),
      confirmTarget: null,
      authText: "",
      authError: "",
      error: "", busy: false,
    };
  },
  computed: {
    rejected() { return this.order.insurance_decision === "rejected"; },
    paused() { return this.order.status === "paused"; },
    canAddChange() { return this.paused; },
    canConvert() { return this.rejected && this.order.status !== "delivered"; },
  },
  methods: {
    fmtMoney, fmtTime, QUOTE_KIND_LABELS, QUOTE_STATUS_LABELS,
    blankForm() {
      return { glass_model: "", glass_spec: "", price_glass: 0, price_labor: 0,
               price_sealant: 0, price_other: 0, insurance_cover: 0, change_reason: "" };
    },
    total(f) {
      return (Number(f.price_glass) + Number(f.price_labor) + Number(f.price_sealant) + Number(f.price_other)).toFixed(2);
    },
    beginConfirm(q) { this.confirmTarget = q; this.authText = ""; this.authError = ""; },
    async doConfirm() {
      if (!this.authText || this.authText.trim().length < 4) {
        this.authError = "请车主本人输入完整授权确认语"; return;
      }
      this.busy = true; this.authError = "";
      try {
        await api(`/api/orders/${this.order.id}/quotes/${this.confirmTarget.version}/confirm`, {
          method: "POST", body: JSON.stringify({ customer_authorization: this.authText }),
        });
        this.confirmTarget = null; this.authText = ""; this.$emit("changed");
      } catch (e) { this.authError = e.message; } finally { this.busy = false; }
    },
    async submitQuote() {
      this.busy = true; this.error = "";
      try {
        await api(`/api/orders/${this.order.id}/quotes`, {
          method: "POST", body: JSON.stringify(this.form),
        });
        this.showForm = false; this.form = this.blankForm(); this.$emit("changed");
      } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
    async submitSelfPay() {
      this.busy = true; this.error = "";
      try {
        await api(`/api/orders/${this.order.id}/convert-self-pay`, {
          method: "POST", body: JSON.stringify({ ...this.sp, change_reason: this.sp.change_reason || "保险拒赔，转自费" }),
        });
        this.showSelfPay = false; this.sp = this.blankForm(); this.$emit("changed");
      } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
    prefillFromLatest(target) {
      const q = this.order.quotes[this.order.quotes.length - 1];
      const f = { glass_model: "", glass_spec: "", price_glass: 0, price_labor: 0,
        price_sealant: 0, price_other: 0, insurance_cover: 0, change_reason: "" };
      if (q) {
        f.glass_model = q.glass_model; f.glass_spec = q.glass_spec;
        f.price_glass = q.price_glass; f.price_labor = q.price_labor;
        f.price_sealant = q.price_sealant; f.price_other = q.price_other;
      }
      if (target === "sp") this.sp = f; else this.form = f;
    },
  },
  template: `
  <div class="card">
    <h2>报价与方案 <span class="sub">同一工单多版本保留；改价/拒赔转自费均需车主重新授权</span></h2>
    <div v-if="error" class="alert error">{{ error }}</div>

    <div v-if="rejected" class="alert error">
      保险公司已拒赔。原保险报价保留备查；继续施工须转为自费并出具新报价，由车主重新确认授权。
    </div>
    <div v-if="paused" class="alert error">
      施工已暂停：{{ order.pause_reason || '型号不符/新破损' }}。须重新说明玻璃方案与费用，车主确认新版报价后方可复工。
    </div>

    <div v-for="q in [...order.quotes].reverse()" :key="q.id"
         class="quote-box" :class="{superseded: q.status==='superseded', current: q.status==='confirmed'}">
      <div class="quote-head">
        <div>
          <strong>第 {{ q.version }} 版 · {{ QUOTE_KIND_LABELS[q.kind] }}</strong>
          <span class="badge" style="margin-left:8px"
                :class="q.status==='confirmed'?'green':q.status==='superseded'?'gray':'orange'">
            {{ QUOTE_STATUS_LABELS[q.status] }}
          </span>
        </div>
        <span class="muted small">出具 {{ fmtTime(q.created_at) }}<template v-if="q.confirmed_at"> · 确认 {{ fmtTime(q.confirmed_at) }}</template></span>
      </div>
      <div class="grid cols-4">
        <div class="kv" style="grid-column:span 2"><span class="k">玻璃型号</span><span class="v">{{ q.glass_model }}</span></div>
        <div class="kv" style="grid-column:span 2"><span class="k">规格</span><span class="v">{{ q.glass_spec || '—' }}</span></div>
        <div class="kv"><span class="k">玻璃</span><span class="v money">{{ fmtMoney(q.price_glass) }}</span></div>
        <div class="kv"><span class="k">工时</span><span class="v money">{{ fmtMoney(q.price_labor) }}</span></div>
        <div class="kv"><span class="k">密封胶</span><span class="v money">{{ fmtMoney(q.price_sealant) }}</span></div>
        <div class="kv"><span class="k">其他</span><span class="v money">{{ fmtMoney(q.price_other) }}</span></div>
      </div>
      <div class="grid cols-3" style="margin-top:10px">
        <div class="kv"><span class="k">报价总额</span><span class="v money">{{ fmtMoney(q.total_amount) }}</span></div>
        <div class="kv"><span class="k">保险承担</span><span class="v money ins">{{ fmtMoney(q.insurance_cover) }}</span></div>
        <div class="kv"><span class="k">车主自付</span><span class="v money self">{{ fmtMoney(q.self_pay) }}</span></div>
      </div>
      <div class="small muted" style="margin-top:8px">说明：{{ q.change_reason }}</div>
      <div v-if="q.customer_authorization" class="small" style="margin-top:4px;color:#14532d">
        ✓ 车主授权：「{{ q.customer_authorization }}」
      </div>
      <div class="btn-row" style="margin-top:10px" v-if="q.status==='pending_customer'">
        <button class="btn ok" @click="beginConfirm(q)">
          请车主确认授权{{ q.kind==='insurance' ? '' : '（改价须重新授权）' }}
        </button>
      </div>
    </div>

    <div class="btn-row" style="margin-top:6px">
      <button v-if="canAddChange && !showForm" class="btn warn" @click="showForm=true; prefillFromLatest('form')">
        出具施工变更报价（型号不符/新破损）
      </button>
      <button v-if="canConvert && !showSelfPay" class="btn danger"
        @click="showSelfPay=true; prefillFromLatest('sp')">
        拒赔转自费：生成新报价
      </button>
    </div>

    <!-- 施工变更报价 -->
    <div v-if="showForm" class="quote-box" style="border-color:#e3b365">
      <strong>变更报价（原版本保留，新版本需车主重新确认）</strong>
      <div class="grid cols-2" style="margin-top:10px">
        <div class="field"><label>玻璃型号 *</label><input v-model="form.glass_model" /></div>
        <div class="field"><label>规格</label><input v-model="form.glass_spec" /></div>
        <div class="field"><label>玻璃费</label><input type="number" v-model.number="form.price_glass" /></div>
        <div class="field"><label>工时费</label><input type="number" v-model.number="form.price_labor" /></div>
        <div class="field"><label>胶费</label><input type="number" v-model.number="form.price_sealant" /></div>
        <div class="field"><label>其他费</label><input type="number" v-model.number="form.price_other" /></div>
        <div class="field" style="grid-column:1/-1"><label>变更原因 *（型号不符/新增破损说明）</label>
          <input v-model="form.change_reason" placeholder="如：实车为带雨感底座版本，需更换型号；另发现右A柱边框锈蚀处理" />
        </div>
      </div>
      <div class="btn-row" style="margin-top:10px">
        <span>合计 <b class="money">{{ fmtMoney(total(form)) }}</b>（施工变更按自费/另议处理，保险承担默认 0）</span>
        <button class="btn" :disabled="busy" @click="submitQuote">出具新报价，等待车主确认</button>
        <button class="btn secondary" @click="showForm=false">取消</button>
      </div>
    </div>

    <!-- 拒赔转自费报价 -->
    <div v-if="showSelfPay" class="quote-box" style="border-color:#e79490">
      <strong>自费新报价（保险承担 ¥0.00，原保险报价保留）</strong>
      <div class="grid cols-2" style="margin-top:10px">
        <div class="field"><label>玻璃型号 *</label><input v-model="sp.glass_model" /></div>
        <div class="field"><label>规格</label><input v-model="sp.glass_spec" /></div>
        <div class="field"><label>玻璃费</label><input type="number" v-model.number="sp.price_glass" /></div>
        <div class="field"><label>工时费</label><input type="number" v-model.number="sp.price_labor" /></div>
        <div class="field"><label>胶费</label><input type="number" v-model.number="sp.price_sealant" /></div>
        <div class="field"><label>其他费</label><input type="number" v-model.number="sp.price_other" /></div>
      </div>
      <div class="btn-row" style="margin-top:10px">
        <span>车主自付 <b class="money self">{{ fmtMoney(total(sp)) }}</b></span>
        <button class="btn danger" :disabled="busy" @click="submitSelfPay">生成自费报价，等待车主重新授权</button>
        <button class="btn secondary" @click="showSelfPay=false">取消</button>
      </div>
    </div>

    <!-- 车主授权弹窗 -->
    <div v-if="confirmTarget" class="modal-mask" @click.self="confirmTarget=null">
      <div class="modal">
        <h3>车主确认授权 —— 第 {{ confirmTarget.version }} 版报价</h3>
        <div class="alert info">
          玻璃：{{ confirmTarget.glass_model }}<br/>
          总额 {{ fmtMoney(confirmTarget.total_amount) }}，保险承担
          <b class="money ins">{{ fmtMoney(confirmTarget.insurance_cover) }}</b>，
          车主自付 <b class="money self">{{ fmtMoney(confirmTarget.self_pay) }}</b>。
        </div>
        <div v-if="confirmTarget.kind !== 'insurance'" class="authorize-hint">
          ⚠ 本次为{{ confirmTarget.kind === 'self_pay' ? '拒赔后转自费' : '施工中方案/费用变更' }}，
          即使此前已授权过，也必须由车主对新报价<b>重新授权</b>。
        </div>
        <div class="field">
          <label>请车主输入授权确认语（本人确认知悉费用并同意）</label>
          <textarea v-model="authText" rows="3"
            placeholder="如：本人张伟已知悉保险拒赔/方案变更，确认玻璃型号与自付金额 ¥0.00，同意自费安装"></textarea>
        </div>
        <div v-if="authError" class="alert error" style="margin-top:8px">{{ authError }}</div>
        <div class="btn-row" style="margin-top:12px">
          <button class="btn ok" :disabled="busy" @click="doConfirm">确认授权</button>
          <button class="btn secondary" @click="confirmTarget=null">返回</button>
        </div>
      </div>
    </div>
  </div>`,
};

/* ============================================================ 施工面板 */
const InstallSection = {
  props: ["order"],
  emits: ["changed"],
  data() {
    return {
      pauseReason: "", showPause: false,
      cureMinutes: 120,
      inspectPassed: true, inspectNote: "",
      error: "", busy: false,
    };
  },
  methods: {
    fmtTime,
    async call(path, body) {
      this.busy = true; this.error = "";
      try {
        await api(`/api/orders/${this.order.id}${path}`,
          body === undefined ? { method: "POST" }
            : { method: "POST", body: JSON.stringify(body) });
        this.showPause = false; this.$emit("changed");
      } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
    async upload(ev) {
      const file = ev.target.files[0];
      if (!file) return;
      this.busy = true; this.error = "";
      try {
        const fd = new FormData();
        fd.append("file", file); fd.append("stage", "install");
        await api(`/api/orders/${this.order.id}/photos`, { method: "POST", body: fd });
        this.$emit("changed");
      } catch (e) { this.error = e.message; } finally { this.busy = false; ev.target.value = ""; }
    },
  },
  template: `
  <div class="card">
    <h2>施工登记 <span class="sub">安装照片 · 胶固化时间 · 验收</span></h2>
    <div v-if="error" class="alert error">{{ error }}</div>

    <div class="grid cols-3">
      <div class="kv"><span class="k">开工时间</span><span class="v">{{ order.status==='created'||order.status==='ready' ? '—' : (order.cure_deadline ? '已开工' : '—') }}</span></div>
      <div class="kv"><span class="k">胶固化截止时间</span>
        <span class="v">{{ order.cure_deadline ? fmtTime(order.cure_deadline) : '未登记' }}</span>
      </div>
      <div class="kv"><span class="k">验收结果</span>
        <span class="v"><span class="badge" :class="order.inspection_result==='pass'?'green':order.inspection_result==='fail'?'red':'gray'">
          {{ order.inspection_result==='pass' ? '验收通过' : order.inspection_result==='fail' ? '验收未过（整改复检）' : '未验收' }}
        </span></span>
      </div>
    </div>
    <div v-if="order.inspection_note" class="small muted" style="margin-top:6px">验收备注：{{ order.inspection_note }}</div>

    <div class="photos">
      <a v-for="p in order.photos" :key="p.id" :href="'/uploads/'+p.filename" target="_blank">
        <img :src="'/uploads/'+p.filename" :alt="p.original_name" />
      </a>
    </div>

    <div class="btn-row" style="margin-top:14px">
      <button v-if="order.status==='scheduled'" class="btn" :disabled="busy" @click="call('/install/start')">开始施工</button>
      <button v-if="order.status==='installing'" class="btn danger" :disabled="busy" @click="showPause=true">暂停：型号不符 / 新破损</button>
      <label v-if="['installing','installed'].includes(order.status)"
             class="btn secondary" style="display:inline-block">
        上传安装照片<input type="file" accept="image/*" style="display:none" @change="upload" />
      </label>
      <button v-if="order.status==='installing'" class="btn secondary" :disabled="busy"
              @click="call('/cure', {cure_minutes: Number(cureMinutes)})">
        登记固化时间（{{ cureMinutes }} 分钟）
      </button>
      <input v-if="order.status==='installing'" type="number" min="1" v-model.number="cureMinutes" style="width:90px" />
      <button v-if="order.status==='installing' && order.photos.length" class="btn ok" :disabled="busy"
              @click="call('/install/finish')">完成安装（进入固化/验收）</button>
      <button v-if="order.status==='paused'" class="btn warn" :disabled="busy" @click="call('/install/resume')">
        复工（须已确认变更报价）
      </button>
    </div>

    <!-- 暂停原因 -->
    <div v-if="showPause" class="quote-box" style="margin-top:12px;border-color:#e79490">
      <div class="field"><label>暂停原因 *</label>
        <textarea v-model="pauseReason" rows="2" placeholder="如：拆下后发现实车玻璃型号与报价不符 / 发现窗框新破损"></textarea>
      </div>
      <div class="btn-row" style="margin-top:8px">
        <button class="btn danger" :disabled="busy || pauseReason.length<2"
          @click="call('/install/pause', {reason: pauseReason})">确认暂停施工</button>
        <button class="btn secondary" @click="showPause=false">继续施工</button>
      </div>
    </div>

    <!-- 验收 -->
    <div v-if="order.status==='installed'" style="margin-top:14px;border-top:1px solid var(--line);padding-top:14px">
      <strong>安装验收</strong>
      <div class="grid cols-2" style="margin-top:8px">
        <div class="field"><label>验收结论</label>
          <select v-model="inspectPassed">
            <option :value="true">合格（密封到位/无渗漏/功能正常）</option>
            <option :value="false">不合格（需整改后复检）</option>
          </select>
        </div>
        <div class="field"><label>验收备注</label><input v-model="inspectNote" /></div>
      </div>
      <button class="btn" style="margin-top:8px" :disabled="busy"
        @click="call('/inspect', {passed: inspectPassed, note: inspectNote})">提交验收结果</button>
    </div>
  </div>`,
};

/* ============================================================ 交车门禁 */
const DeliverySection = {
  props: ["order"],
  emits: ["changed"],
  data() { return { operator: "", error: "", busy: false }; },
  methods: {
    fmtTime,
    async deliver() {
      this.busy = true; this.error = "";
      try {
        await api(`/api/orders/${this.order.id}/deliver`, {
          method: "POST", body: JSON.stringify({ operator: this.operator }),
        });
        this.$emit("changed");
      } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
  },
  template: `
  <div class="card">
    <h2>交车放行 <span class="sub">四项硬性条件全部满足方可交车，服务端强制拦截</span></h2>

    <div :class="['alert', order.delivery_gate.allow ? 'gate-ok' : 'gate-block']">
      <strong style="font-size:15px">
        {{ order.status === 'delivered' ? '✅ 车辆已交车'
           : (order.delivery_gate.allow ? '✅ 当前允许交付车辆' : '⛔ 当前不允许交付车辆') }}
      </strong>
      <ul class="gate-list">
        <li>
          <span :class="order.delivery_gate.cured ? 'yes' : 'no'">{{ order.delivery_gate.cured ? '✓' : '✗' }}</span>
          胶已固化
          <span v-if="!order.delivery_gate.cured && order.delivery_gate.minutes_until_cured" class="countdown">
            （剩余约 {{ order.delivery_gate.minutes_until_cured }} 分钟，截止 {{ fmtTime(order.cure_deadline) }}）
          </span>
        </li>
        <li>
          <span :class="order.delivery_gate.inspection_passed ? 'yes' : 'no'">{{ order.delivery_gate.inspection_passed ? '✓' : '✗' }}</span>
          安装验收通过
        </li>
        <li>
          <span :class="order.delivery_gate.photos_ok ? 'yes' : 'no'">{{ order.delivery_gate.photos_ok ? '✓' : '✗' }}</span>
          安装照片已上传（{{ order.photos.length }} 张）
        </li>
        <li>
          <span :class="order.delivery_gate.confirmed_quote_ok ? 'yes' : 'no'">{{ order.delivery_gate.confirmed_quote_ok ? '✓' : '✗' }}</span>
          当前报价已由车主授权确认（拒赔改价须重新授权）
        </li>
      </ul>
      <ul v-if="order.delivery_gate.reasons.length && order.status!=='delivered'">
        <li v-for="(r,i) in order.delivery_gate.reasons" :key="i">{{ r }}</li>
      </ul>
    </div>

    <div v-if="order.status==='delivered'" class="alert success">
      交车时间 {{ fmtTime(order.delivered_at) }}，经办人：{{ order.delivered_by || '—' }}
    </div>

    <div v-else-if="order.status==='installed'" class="btn-row">
      <div class="field" style="width:200px"><label>交车经办人</label><input v-model="operator" /></div>
      <button class="btn ok" :disabled="busy || !order.delivery_gate.allow" @click="deliver">
        {{ order.delivery_gate.allow ? '确认交车' : '未满足放行条件，禁止交车' }}
      </button>
      <span v-if="!order.delivery_gate.allow" class="small muted">按钮由系统门禁锁定；即使强行调用接口，服务端也会拒绝。</span>
    </div>
    <div v-else class="muted small">完成安装、固化到期且验收合格后，在此交车。</div>
    <div v-if="error" class="alert error" style="margin-top:10px">服务端拦截：{{ error }}</div>
  </div>`,
};

/* ============================================================ 保险回执 + 模拟推送 */
const InsuranceSection = {
  props: ["order"],
  emits: ["changed"],
  data() {
    return {
      showSim: false,
      sim: { decision: "approved", cover_amount: 0, reason: "", issued_minutes_ago: 0 },
      error: "", busy: false,
    };
  },
  methods: {
    fmtTime,
    async push() {
      this.busy = true; this.error = "";
      try {
        await api("/api/sim/insurance/receipt", {
          method: "POST", body: JSON.stringify({ claim_no: this.order.claim_no, ...this.sim }),
        });
        this.showSim = false;
        this.sim = { decision: "approved", cover_amount: 0, reason: "", issued_minutes_ago: 0 };
        this.$emit("changed");
      } catch (e) { this.error = e.message; } finally { this.busy = false; }
    },
  },
  template: `
  <div class="card">
    <h2>保险理赔回执 <span class="sub">模拟接口推送 · 迟到回执只留痕不覆盖已确认方案</span></h2>
    <div v-if="error" class="alert error">{{ error }}</div>

    <div class="grid cols-3" style="margin-bottom:10px">
      <div class="kv"><span class="k">保险公司</span><span class="v">{{ order.insurance_company || '—' }}</span></div>
      <div class="kv"><span class="k">报案号</span><span class="v">{{ order.claim_no || '—（未走保险）' }}</span></div>
      <div class="kv"><span class="k">当前理赔状态</span>
        <span class="v"><span class="badge" :class="order.insurance_decision==='approved'?'green':order.insurance_decision==='rejected'?'red':'gray'">{{ INS_LABELS[order.insurance_decision] }}</span></span>
      </div>
    </div>

    <div v-if="!order.receipts.length" class="muted small">尚未收到回执。</div>
    <div v-for="r in [...order.receipts].reverse()" :key="r.id" class="quote-box"
         :class="{superseded: !r.applied}" style="margin-bottom:8px">
      <div class="quote-head">
        <div>
          <span class="badge" :class="r.decision==='approved'?'green':'red'">
            {{ r.decision==='approved' ? '同意赔付 ' + fmtMoney(r.cover_amount) : '拒赔' }}
          </span>
          <span class="badge" style="margin-left:6px" :class="r.applied?'blue':'orange'">{{ r.applied ? '已应用到工单' : '未应用（留痕）' }}</span>
        </div>
        <span class="muted small">签发 {{ fmtTime(r.issued_at) }} · 到店 {{ fmtTime(r.received_at) }}</span>
      </div>
      <div v-if="r.reason" class="small muted">原因：{{ r.reason }}</div>
      <div v-if="r.ignore_reason" class="receipt-ignored">⛔ {{ r.ignore_reason }}</div>
    </div>

    <div v-if="order.claim_no && order.status!=='delivered'" style="margin-top:10px">
      <button v-if="!showSim" class="btn ghost" @click="showSim=true">模拟保险公司推送回执</button>
    </div>
    <div v-if="showSim" class="quote-box" style="border-color:#c7d9fc;margin-top:8px">
      <strong>模拟理赔接口（按报案号 {{ order.claim_no }} 推送）</strong>
      <div class="grid cols-2" style="margin-top:8px">
        <div class="field"><label>结论</label>
          <select v-model="sim.decision">
            <option value="approved">同意赔付</option>
            <option value="rejected">拒赔</option>
          </select>
        </div>
        <div class="field" v-if="sim.decision==='approved'"><label>赔付金额</label>
          <input type="number" v-model.number="sim.cover_amount" />
        </div>
        <div class="field"><label>备注/拒赔原因</label><input v-model="sim.reason" /></div>
        <div class="field"><label>回执签发于多少分钟前（模拟迟到）</label>
          <input type="number" min="0" v-model.number="sim.issued_minutes_ago" />
        </div>
      </div>
      <div class="small muted" style="margin-top:6px">
        先让车主确认改价方案，再把此处设为较大分钟数推送“迟到的同意赔付回执”，可验证它不会覆盖已确认方案。
      </div>
      <div class="btn-row" style="margin-top:8px">
        <button class="btn" :disabled="busy" @click="push">推送回执</button>
        <button class="btn secondary" @click="showSim=false">取消</button>
      </div>
    </div>
  </div>`,
};

/* ============================================================ 工单详情 */
const OrderDetail = {
  props: ["id"],
  emits: ["back"],
  components: { QuoteSection, InstallSection, DeliverySection, InsuranceSection },
  data() { return { order: null, error: "", timer: null, STEPS }; },
  computed: {
    stepIndex() {
      const s = this.order.status;
      if (s === "paused") return STEPS.findIndex((x) => x[0] === "installing");
      return STEPS.findIndex((x) => x[0] === s);
    },
  },
  created() { this.load(); this.timer = setInterval(() => this.load(true), 15000); },
  unmounted() { clearInterval(this.timer); },
  methods: {
    STATUS_LABELS, STATUS_CLASS, fmtTime,
    async load(silent) {
      try { this.order = await api(`/api/orders/${this.id}`); }
      catch (e) { if (!silent) this.error = e.message; }
    },
    async action(path, body) {
      this.error = "";
      try {
        await api(path, body === undefined ? { method: "POST" }
          : { method: "POST", body: JSON.stringify(body) });
        await this.load();
      } catch (e) { this.error = e.message; }
    },
  },
  template: `
  <div v-if="order">
    <span class="back-link" @click="$emit('back')">← 返回工单列表</span>
    <div class="card">
      <div class="quote-head">
        <div>
          <h2 style="margin:0">{{ order.order_no }}
            <span class="badge" :class="STATUS_CLASS[order.status]">{{ STATUS_LABELS[order.status] }}</span>
            <span v-if="order.status==='paused'" class="badge red">暂停：{{ order.pause_reason }}</span>
          </h2>
          <div class="muted small" style="margin-top:4px">
            {{ order.plate_no }} · {{ order.car_model }} · {{ order.glass_position }} ·
            车主 {{ order.customer_name }}（{{ order.customer_phone }}）
          </div>
        </div>
        <div class="muted small">创建 {{ fmtTime(order.created_at) }}</div>
      </div>
      <div class="step-bar">
        <div v-for="(s,i) in STEPS" :key="s[0]" class="step"
             :class="{done: i < stepIndex, active: i === stepIndex}">
          <span class="dot"></span>{{ s[1] }}
        </div>
      </div>
      <div v-if="order.note" class="small muted">接车备注：{{ order.note }}</div>

      <div class="btn-row" style="margin-top:10px">
        <button v-if="!order.stock_confirmed && ['created','ready'].includes(order.status)"
                class="btn secondary" @click="action('/api/orders/'+order.id+'/stock')">
          ✓ 门店确认库存
        </button>
        <span v-else-if="order.stock_confirmed" class="badge green">库存已确认（{{ fmtTime(order.stock_confirmed_at) }}）</span>
        <button v-if="order.status==='created' || order.status==='ready'"
                class="btn" @click="action('/api/orders/'+order.id+'/schedule', {worker:''})">
          安排施工
        </button>
        <span class="small muted">（须同时满足：库存已确认 + 车主已确认报价 + 保险方案通过）</span>
      </div>
      <div v-if="error" class="alert error" style="margin-top:8px">{{ error }}</div>
    </div>

    <QuoteSection :order="order" @changed="load()" />
    <InstallSection :order="order" @changed="load()" />
    <DeliverySection :order="order" @changed="load()" />
    <InsuranceSection :order="order" @changed="load()" />
  </div>
  <div v-else-if="error" class="alert error">{{ error }}</div>`,
};

/* ============================================================ 车主查询 */
const OwnerView = {
  data() {
    return { keyword: "", order: null, error: "", timer: null };
  },
  unmounted() { clearInterval(this.timer); },
  methods: {
    fmtMoney, fmtTime, STATUS_LABELS, STATUS_CLASS,
    async search() {
      this.error = ""; this.order = null;
      try {
        const list = await api("/api/orders?phone=" + encodeURIComponent(this.keyword));
        let hit = list[0];
        if (!hit) hit = await api("/api/orders/" + encodeURIComponent(this.keyword)).catch(() => null);
        if (!hit) { this.error = "未查询到工单，请输入工单号或预留手机号"; return; }
        this.order = hit;
        clearInterval(this.timer);
        this.timer = setInterval(async () => {
          this.order = await api(`/api/orders/${this.order.id}`);
        }, 20000);
      } catch (e) { this.error = e.message; }
    },
  },
  template: `
  <div class="ownerview">
    <div class="card">
      <h2>车主进度查询 <span class="sub">查看玻璃型号、费用构成与预计提车时间</span></h2>
      <div class="btn-row">
        <input v-model="keyword" placeholder="输入工单号（如 WO20261004001）或预留手机号"
               style="width:340px" @keyup.enter="search" />
        <button class="btn" @click="search">查询</button>
      </div>
      <div v-if="error" class="alert error" style="margin-top:10px">{{ error }}</div>
    </div>

    <div v-if="order" class="card">
      <div class="quote-head">
        <h2 style="margin:0">{{ order.order_no }} · {{ order.plate_no }}
          <span class="badge" :class="STATUS_CLASS[order.status]">{{ STATUS_LABELS[order.status] }}</span>
        </h2>
        <span class="muted small">{{ order.car_model }} · {{ order.glass_position }}</span>
      </div>

      <div class="grid cols-4" style="margin-top:14px">
        <div class="amount-card" style="grid-column:span 2">
          <div class="muted small">将安装的玻璃型号</div>
          <div style="font-size:16px;font-weight:600;margin-top:4px">{{ order.current_glass_model || '方案待确认' }}</div>
        </div>
        <div class="amount-card primary"><div class="muted small">报价总额</div>
          <div class="money big">{{ fmtMoney(order.current_total) }}</div></div>
        <div class="amount-card"><div class="muted small">预计可提车</div>
          <div style="font-size:14px;font-weight:600;margin-top:4px">{{ order.eta || (order.status==='delivered' ? '已可提车' : '待施工排期') }}</div></div>
        <div class="amount-card"><div class="muted small">保险承担</div>
          <div class="money big ins">{{ fmtMoney(order.current_insurance_cover) }}</div></div>
        <div class="amount-card"><div class="muted small">车主自付</div>
          <div class="money big self">{{ fmtMoney(order.current_self_pay) }}</div></div>
        <div class="amount-card" style="grid-column:span 2">
          <div class="muted small">交车状态</div>
          <div style="margin-top:4px">
            <span v-if="order.status==='delivered'" class="badge green">✅ 已交车</span>
            <span v-else-if="order.delivery_gate.allow" class="badge green">✅ 已具备提车条件，请等待门店通知</span>
            <span v-else class="badge orange">⏳ {{ order.delivery_gate.reasons[0] || '处理中' }}</span>
          </div>
        </div>
      </div>
      <div class="alert info" style="margin-top:14px">
        安全提示：玻璃安装后胶需要充分固化，未到固化截止时间提前用车存在脱落/漏水风险，
        系统在固化到期且验收合格前不会放行车辆。
      </div>
      <div v-if="order.status==='paused'" class="alert error" style="margin-top:0">
        施工中发现情况（{{ order.pause_reason }}），门店已暂停施工并将与您重新确认玻璃方案和费用，
        新方案需您本人再次授权。
      </div>
    </div>
  </div>`,
};

/* ============================================================ 根组件 */
const App = {
  components: { OrderList, NewOrder, OrderDetail, OwnerView },
  data() {
    return { tab: "shop", view: { name: "list", id: null } };
  },
  methods: {
    gotoList() { this.view = { name: "list" }; },
    openOrder(id) { this.view = { name: "detail", id }; },
  },
  template: `
  <header class="topbar">
    <h1>🚗 汽车玻璃保险直赔与安装验收系统</h1>
    <nav>
      <button :class="{active: tab==='shop'}" @click="tab='shop'; gotoList()">门店工作台</button>
      <button :class="{active: tab==='owner'}" @click="tab='owner'">车主查询</button>
    </nav>
  </header>
  <div class="container">
    <template v-if="tab==='shop'">
      <NewOrder v-if="view.name==='new'" @created="openOrder" @cancel="gotoList" />
      <OrderDetail v-else-if="view.name==='detail'" :id="view.id" @back="gotoList" />
      <OrderList v-else @open="openOrder" @new="view={name:'new'}" />
    </template>
    <OwnerView v-else />
  </div>`,
};

const app = createApp(App);
// 让所有模板可以直接使用的常量/格式化函数
app.config.globalProperties.STATUS_LABELS = STATUS_LABELS;
app.config.globalProperties.STATUS_CLASS = STATUS_CLASS;
app.config.globalProperties.QUOTE_KIND_LABELS = QUOTE_KIND_LABELS;
app.config.globalProperties.QUOTE_STATUS_LABELS = QUOTE_STATUS_LABELS;
app.config.globalProperties.INS_LABELS = INS_LABELS;
app.config.globalProperties.fmtMoney = fmtMoney;
app.config.globalProperties.fmtTime = fmtTime;
app.mount("#app");

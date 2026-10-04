/* 汽车玻璃保险直赔与安装验收系统 —— 前端（Vue 3 全局构建，无打包步骤） */
const { createApp, ref, reactive, computed, onMounted, onUnmounted, watch } = Vue;

/* ---------------- 通用 ---------------- */
const bus = reactive({ msg: '' });
let busTimer = null;
function notify(m) {
  bus.msg = m;
  clearTimeout(busTimer);
  busTimer = setTimeout(() => { bus.msg = ''; }, 3200);
}

async function api(path, opts) {
  opts = opts || {};
  const o = { method: opts.method || 'GET' };
  if (opts.form) {
    o.body = opts.form;
  } else if (opts.body !== undefined) {
    o.headers = { 'Content-Type': 'application/json' };
    o.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, o);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch (e) { data = text; }
  if (!res.ok) {
    let msg = (data && data.detail) || res.statusText;
    if (typeof msg === 'object') msg = JSON.stringify(msg);
    throw new Error(msg);
  }
  return data;
}

function fmtDT(s) {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleString('zh-CN', { hour12: false });
}
function money(n) {
  if (n === null || n === undefined) return '—';
  return '¥' + Number(n).toFixed(2);
}
function toLocalInput(d) {
  const p = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
    'T' + p(d.getHours()) + ':' + p(d.getMinutes());
}

const STATUS_COLORS = {
  INTAKE: 'gray', QUOTE_PENDING: 'orange', CONFIRMED: 'blue',
  INSURANCE_REVIEW: 'purple', DENIED: 'red', READY: 'green',
  IN_PROGRESS: 'blue', PAUSED: 'red', INSTALLED: 'orange', DELIVERED: 'green',
};
const QUOTE_STATUS_COLORS = { PENDING_OWNER: 'orange', CONFIRMED: 'green', SUPERSEDED: 'gray' };
const CLAIM_STATUS_COLORS = { SUBMITTED: 'purple', APPROVED: 'green', DENIED: 'red', STALE: 'gray' };
const REASONS = [
  { value: 'DENIAL_CONVERT', label: '拒赔转自费' },
  { value: 'MODEL_MISMATCH', label: '型号不符' },
  { value: 'NEW_DAMAGE', label: '新发现破损' },
  { value: 'OWNER_REQUEST', label: '车主变更方案' },
];

/* ---------------- 工单列表 ---------------- */
const ListView = {
  data() { return { items: [], error: '', loading: true }; },
  async mounted() { await this.load(); },
  methods: {
    async load() {
      this.loading = true;
      try { this.items = (await api('/api/workorders')).items; }
      catch (e) { this.error = e.message; }
      this.loading = false;
    },
    go(id) { location.hash = '#/wo/' + id; },
  },
  template: `
  <div>
    <div class="page-head">
      <h2>工单列表</h2>
      <div class="row">
        <button class="btn" @click="load">刷新</button>
        <a class="btn primary" href="#/new">+ 新建工单</a>
      </div>
    </div>
    <div v-if="error" class="alert-error">{{ error }}</div>
    <div class="card" style="padding:0">
      <table class="tbl">
        <thead><tr>
          <th>工单号</th><th>车牌</th><th>车主</th><th>玻璃型号</th>
          <th>金额</th><th>状态</th><th>预计提车</th><th>创建时间</th>
        </tr></thead>
        <tbody>
          <tr v-for="w in items" :key="w.id" class="clickable" @click="go(w.id)">
            <td class="mono">{{ w.order_no }}</td>
            <td>{{ w.plate_number }}</td>
            <td>{{ w.owner_name }}</td>
            <td>{{ w.glass_model || '—' }}</td>
            <td>{{ money(w.total) }}</td>
            <td><span class="badge" :class="STATUS_COLORS[w.status] || 'gray'">{{ w.status_label }}</span></td>
            <td>{{ fmtDT(w.estimated_pickup_at) }}</td>
            <td>{{ fmtDT(w.created_at) }}</td>
          </tr>
          <tr v-if="!items.length && !loading"><td colspan="8" class="muted" style="text-align:center;padding:26px">暂无工单，点击右上角「新建工单」开始</td></tr>
        </tbody>
      </table>
    </div>
  </div>`,
};

/* ---------------- 新建工单 ---------------- */
const NewView = {
  data() {
    const tomorrow = new Date(Date.now() + 24 * 3600 * 1000);
    tomorrow.setHours(18, 0, 0, 0);
    return {
      inventory: [],
      error: '',
      form: {
        plate_number: '', owner_name: '', owner_phone: '', vehicle_model: '',
        glass_model: '', damage_desc: '',
        estimated_pickup_at: toLocalInput(tomorrow),
        glass_price: 1800, labor_fee: 500, other_fee: 100,
        payment_method: 'INSURANCE', insurance_amount: 2000, note: '',
      },
    };
  },
  computed: {
    total() {
      return (Number(this.form.glass_price) || 0) + (Number(this.form.labor_fee) || 0) +
        (Number(this.form.other_fee) || 0);
    },
    selfPay() {
      if (this.form.payment_method === 'SELF_PAY') return this.total;
      return Math.max(0, this.total - (Number(this.form.insurance_amount) || 0));
    },
  },
  async mounted() {
    try { this.inventory = (await api('/api/inventory')).items; } catch (e) { /* 忽略 */ }
  },
  methods: {
    async submit() {
      this.error = '';
      try {
        const body = Object.assign({}, this.form, {
          estimated_pickup_at: this.form.estimated_pickup_at
            ? new Date(this.form.estimated_pickup_at).toISOString() : null,
        });
        const wo = await api('/api/workorders', { method: 'POST', body });
        notify('工单已创建，请将车主页链接发给车主确认报价');
        location.hash = '#/wo/' + wo.id;
      } catch (e) { this.error = e.message; }
    },
  },
  template: `
  <div>
    <div class="page-head"><h2>新建工单（接车报价）</h2><a class="btn" href="#/">返回列表</a></div>
    <div class="card">
      <h3>车辆与车主</h3>
      <div class="form-grid">
        <div><label>车牌号 *</label><input v-model="form.plate_number" placeholder="沪A·D12345"></div>
        <div><label>车主姓名 *</label><input v-model="form.owner_name"></div>
        <div><label>联系电话</label><input v-model="form.owner_phone"></div>
        <div><label>车型</label><input v-model="form.vehicle_model" placeholder="丰田凯美瑞 2020 款"></div>
        <div><label>玻璃型号 *（可从库存选择）</label>
          <input v-model="form.glass_model" list="glass-list" placeholder="FW-CAMRY-2020">
          <datalist id="glass-list">
            <option v-for="i in inventory" :value="i.glass_model">{{ i.name }}（可用 {{ i.available }}）</option>
          </datalist>
        </div>
        <div><label>预计提车时间</label><input type="datetime-local" v-model="form.estimated_pickup_at"></div>
        <div class="full"><label>损伤描述</label><textarea rows="2" v-model="form.damage_desc" placeholder="前挡玻璃被石子击中，裂纹约 15cm"></textarea></div>
      </div>
    </div>
    <div class="card">
      <h3>初始报价</h3>
      <div class="form-grid">
        <div><label>玻璃价格（元）</label><input type="number" min="0" step="0.01" v-model="form.glass_price"></div>
        <div><label>工时费（元）</label><input type="number" min="0" step="0.01" v-model="form.labor_fee"></div>
        <div><label>其他费用（元）</label><input type="number" min="0" step="0.01" v-model="form.other_fee"></div>
        <div><label>支付方式</label>
          <select v-model="form.payment_method">
            <option value="INSURANCE">保险直赔</option>
            <option value="SELF_PAY">车主自费</option>
          </select>
        </div>
        <div v-if="form.payment_method === 'INSURANCE'"><label>保险承担（元）</label>
          <input type="number" min="0" step="0.01" v-model="form.insurance_amount"></div>
        <div><label>方案说明</label><input v-model="form.note" placeholder="初始报价"></div>
      </div>
      <div class="alert-info mt14">
        合计 <b>{{ money(total) }}</b> ｜ 保险承担 <b>{{ form.payment_method === 'INSURANCE' ? money(form.insurance_amount) : '¥0.00' }}</b> ｜ 车主自付 <b>{{ money(selfPay) }}</b>
        <div class="muted mt8">创建后需车主在车主页确认报价（授权），才能提交保险理赔与安排施工。</div>
      </div>
      <div v-if="error" class="alert-error">{{ error }}</div>
      <div class="form-actions">
        <button class="btn primary" @click="submit">创建工单</button>
        <a class="btn" href="#/">取消</a>
      </div>
    </div>
  </div>`,
};

/* ---------------- 工单详情 ---------------- */
const DetailView = {
  props: ['id'],
  data() {
    return {
      wo: null, error: '', actionError: '', tab: 'overview',
      inventory: [], pollResult: null, timer: null,
      showQuoteForm: false,
      quoteForm: { reason: 'DENIAL_CONVERT', glass_model: '', glass_price: 0, labor_fee: 0, other_fee: 0, payment_method: 'SELF_PAY', insurance_amount: 0, note: '' },
      claimForm: { delay_seconds: 10, force_decision: '' },
      pauseForm: { reason: 'MODEL_MISMATCH', note: '' },
      finishForm: { glue_type: '聚氨酯结构胶', curing: '' },
      acceptForm: { result: 'PASSED', note: '' },
      photoStage: 'AFTER',
      editPickup: '', editingPickup: false,
      REASONS,
    };
  },
  computed: {
    confirmedQuote() {
      if (!this.wo) return null;
      return this.wo.quotes.find(q => q.status === 'CONFIRMED') || null;
    },
    latestQuote() {
      if (!this.wo || !this.wo.quotes.length) return null;
      return this.wo.quotes[this.wo.quotes.length - 1];
    },
    startBlockers() {
      const wo = this.wo, b = [];
      if (!wo) return b;
      const cq = this.confirmedQuote;
      if (!cq) { b.push('报价未获车主确认'); return b; }
      if (!(wo.inventory.confirmed && wo.inventory.reserved_model === cq.glass_model))
        b.push('库存未确认（需 ' + cq.glass_model + '）');
      if (cq.payment_method === 'INSURANCE') {
        const ok = wo.claims.some(c => c.quote_revision === cq.revision && c.status === 'APPROVED');
        if (!ok) b.push('保险方案未批复');
      }
      return b;
    },
    curingInfo() {
      const inst = this.wo && this.wo.installation;
      if (!inst || !inst.curing_deadline) return null;
      const dl = new Date(inst.curing_deadline), now = new Date();
      const mins = Math.round((dl - now) / 60000);
      return mins <= 0
        ? { ok: true, text: '固化时间已到（' + fmtDT(inst.curing_deadline) + '）' }
        : { ok: false, text: '固化中，剩余约 ' + mins + ' 分钟（截止 ' + fmtDT(inst.curing_deadline) + '）' };
    },
  },
  watch: {
    'quoteForm.reason'(r) {
      if (r === 'DENIAL_CONVERT') this.quoteForm.payment_method = 'SELF_PAY';
    },
  },
  async mounted() {
    await this.load();
    try { this.inventory = (await api('/api/inventory')).items; } catch (e) { /* 忽略 */ }
    this.timer = setInterval(() => { if (!document.hidden) this.load(true); }, 5000);
  },
  unmounted() { clearInterval(this.timer); },
  methods: {
    async load(quiet) {
      try { this.wo = await api('/api/workorders/' + this.id); this.error = ''; }
      catch (e) { this.error = e.message; }
    },
    async act(fn, okMsg) {
      this.actionError = '';
      try { await fn(); await this.load(); if (okMsg) notify(okMsg); }
      catch (e) { this.actionError = e.message; }
    },
    openQuoteForm() {
      const lq = this.latestQuote;
      if (lq) {
        this.quoteForm.glass_model = lq.glass_model;
        this.quoteForm.glass_price = lq.glass_price;
        this.quoteForm.labor_fee = lq.labor_fee;
        this.quoteForm.other_fee = lq.other_fee;
      }
      this.showQuoteForm = true;
    },
    submitQuote() {
      return this.act(async () => {
        await api('/api/workorders/' + this.id + '/quotes', { method: 'POST', body: this.quoteForm });
        this.showQuoteForm = false;
        this.quoteForm.note = '';
      }, '新报价已生成，等待车主确认授权');
    },
    submitClaim() {
      return this.act(async () => {
        const body = { delay_seconds: Number(this.claimForm.delay_seconds) || 0 };
        if (this.claimForm.force_decision) body.force_decision = this.claimForm.force_decision;
        await api('/api/workorders/' + this.id + '/claims', { method: 'POST', body });
      }, '理赔已提交保险公司，等待回执');
    },
    poll() {
      return this.act(async () => {
        this.pollResult = await api('/api/insurance/poll', { method: 'POST' });
      }, '已刷新保险回执');
    },
    confirmInventory() {
      return this.act(() => api('/api/workorders/' + this.id + '/inventory/confirm', { method: 'POST' }), '库存已确认');
    },
    startWork() {
      return this.act(() => api('/api/workorders/' + this.id + '/start-work', { method: 'POST' }), '已开始施工');
    },
    pauseWork() {
      return this.act(async () => {
        await api('/api/workorders/' + this.id + '/pause', { method: 'POST', body: this.pauseForm });
        this.pauseForm.note = '';
      }, '施工已暂停，请生成新方案并由车主确认');
    },
    resumeWork() {
      return this.act(() => api('/api/workorders/' + this.id + '/resume', { method: 'POST' }), '已恢复施工');
    },
    uploadPhoto() {
      return this.act(async () => {
        const input = this.$refs.fileInput;
        if (!input.files.length) throw new Error('请选择照片文件');
        const fd = new FormData();
        fd.append('file', input.files[0]);
        fd.append('stage', this.photoStage);
        await api('/api/workorders/' + this.id + '/photos', { method: 'POST', form: fd });
        input.value = '';
      }, '照片已上传');
    },
    finishWork() {
      return this.act(async () => {
        if (!this.finishForm.curing) throw new Error('请选择固化截止时间');
        await api('/api/workorders/' + this.id + '/installation/finish', {
          method: 'POST',
          body: { glue_type: this.finishForm.glue_type, curing_deadline: new Date(this.finishForm.curing).toISOString() },
        });
      }, '已登记安装完成与固化截止时间');
    },
    submitAcceptance() {
      return this.act(async () => {
        await api('/api/workorders/' + this.id + '/installation/acceptance', { method: 'POST', body: this.acceptForm });
        this.acceptForm.note = '';
      }, '验收结果已登记');
    },
    deliver() {
      if (!confirm('确认交付车辆？交付后工单将关闭。')) return;
      return this.act(() => api('/api/workorders/' + this.id + '/deliver', { method: 'POST' }), '车辆已交付');
    },
    savePickup() {
      return this.act(async () => {
        if (!this.editPickup) throw new Error('请选择时间');
        await api('/api/workorders/' + this.id + '/estimated-pickup', {
          method: 'PUT', body: { estimated_pickup_at: new Date(this.editPickup).toISOString() },
        });
        this.editingPickup = false;
      }, '预计提车时间已更新');
    },
    outcomeLabel(o) {
      return { applied: '已应用', stale: '迟到回执·已忽略', duplicate: '重复回执·已忽略', unknown: '未知理赔号' }[o] || o;
    },
  },
  template: `
  <div v-if="wo">
    <div class="page-head">
      <h2>{{ wo.order_no }} <span class="badge" :class="STATUS_COLORS[wo.status] || 'gray'">{{ wo.status_label }}</span></h2>
      <div class="row">
        <a class="btn" :href="wo.owner_path" target="_blank">车主页 ↗</a>
        <a class="btn" href="#/">返回列表</a>
      </div>
    </div>
    <div v-if="actionError" class="alert-error">{{ actionError }}</div>

    <div class="tabs">
      <a :class="{active: tab==='overview'}" @click="tab='overview'">概览</a>
      <a :class="{active: tab==='plan'}" @click="tab='plan'">报价与保险</a>
      <a :class="{active: tab==='work'}" @click="tab='work'">施工</a>
      <a :class="{active: tab==='delivery'}" @click="tab='delivery'">交车</a>
    </div>

    <!-- 概览 -->
    <div v-if="tab==='overview'">
      <div class="grid2">
        <div class="card">
          <h3>车辆信息</h3>
          <div class="kv">
            <span class="k">车牌</span><span class="v">{{ wo.plate_number }}</span>
            <span class="k">车主</span><span class="v">{{ wo.owner_name }}（{{ wo.owner_phone || '无电话' }}）</span>
            <span class="k">车型</span><span class="v">{{ wo.vehicle_model || '—' }}</span>
            <span class="k">损伤</span><span class="v">{{ wo.damage_desc || '—' }}</span>
            <span class="k">预计提车</span>
            <span class="v">{{ fmtDT(wo.estimated_pickup_at) }}
              <a v-if="wo.status!=='DELIVERED'" href="javascript:;" class="mono" @click="editingPickup=!editingPickup; editPickup=''">修改</a>
            </span>
          </div>
          <div v-if="editingPickup" class="row mt8">
            <input type="datetime-local" v-model="editPickup" style="width:auto">
            <button class="btn small primary" @click="savePickup">保存</button>
          </div>
        </div>
        <div class="card">
          <h3>当前方案</h3>
          <template v-if="confirmedQuote">
            <div class="big-amounts">
              <div class="item"><div class="num">{{ confirmedQuote.glass_model }}</div><div class="lbl">玻璃型号</div></div>
              <div class="item"><div class="num">{{ money(confirmedQuote.total) }}</div><div class="lbl">总价</div></div>
              <div class="item"><div class="num">{{ money(confirmedQuote.insurance_amount) }}</div><div class="lbl">保险承担</div></div>
              <div class="item"><div class="num" style="color:var(--orange)">{{ money(confirmedQuote ? confirmedQuote.self_pay_amount : 0) }}</div><div class="lbl">车主自付</div></div>
            </div>
            <div class="mt8 muted">第 {{ confirmedQuote.revision }} 版 · {{ confirmedQuote.reason_label }} · {{ confirmedQuote.payment_label }} · 确认于 {{ fmtDT(confirmedQuote.confirmed_at) }}</div>
          </template>
          <div v-else class="alert-warn">当前没有已确认的报价<span v-if="latestQuote">（第 {{ latestQuote.revision }} 版等待车主确认授权）</span>。</div>
        </div>
      </div>
      <div class="card">
        <h3>事件日志</h3>
        <ul class="timeline">
          <li v-for="e in wo.events" :key="e.id">
            <div>{{ e.message }}</div>
            <div class="t">{{ fmtDT(e.created_at) }} · {{ e.type }}</div>
          </li>
        </ul>
      </div>
    </div>

    <!-- 报价与保险 -->
    <div v-if="tab==='plan'">
      <div class="card">
        <h3>报价版本（历史版本保留）</h3>
        <table class="tbl">
          <thead><tr><th>版本</th><th>原因</th><th>玻璃型号</th><th>总价</th><th>保险承担</th><th>车主自付</th><th>支付</th><th>状态</th><th>说明</th><th>时间</th></tr></thead>
          <tbody>
            <tr v-for="q in wo.quotes" :key="q.id">
              <td>第 {{ q.revision }} 版</td>
              <td>{{ q.reason_label }}</td>
              <td>{{ q.glass_model }}</td>
              <td>{{ money(q.total) }}</td>
              <td>{{ money(q.insurance_amount) }}</td>
              <td>{{ money(q.self_pay_amount) }}</td>
              <td>{{ q.payment_label }}</td>
              <td><span class="badge" :class="QUOTE_STATUS_COLORS[q.status]">{{ q.status_label }}</span></td>
              <td class="muted">{{ q.note }}</td>
              <td class="muted">{{ fmtDT(q.created_at) }}<br>{{ q.confirmed_at ? '确认 ' + fmtDT(q.confirmed_at) : '' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="latestQuote && latestQuote.status==='PENDING_OWNER'" class="alert-warn mt8">
          第 {{ latestQuote.revision }} 版报价等待车主确认授权。请将车主页链接发给车主：
          <a :href="wo.owner_path" target="_blank">{{ wo.owner_path }}</a>
        </div>
        <div class="form-actions" v-if="wo.status!=='DELIVERED'">
          <button class="btn" @click="openQuoteForm" v-if="!showQuoteForm">+ 生成新报价（转自费 / 型号不符 / 新破损 / 方案变更）</button>
        </div>
        <div v-if="showQuoteForm" class="mt14" style="border-top:1px dashed var(--border);padding-top:12px">
          <div class="form-grid">
            <div><label>变更原因</label>
              <select v-model="quoteForm.reason">
                <option v-for="r in REASONS" :value="r.value">{{ r.label }}</option>
              </select>
            </div>
            <div><label>玻璃型号</label>
              <input v-model="quoteForm.glass_model" list="glass-list2">
              <datalist id="glass-list2">
                <option v-for="i in inventory" :value="i.glass_model">{{ i.name }}（可用 {{ i.available }}）</option>
              </datalist>
            </div>
            <div><label>支付方式</label>
              <select v-model="quoteForm.payment_method" :disabled="quoteForm.reason==='DENIAL_CONVERT'">
                <option value="INSURANCE">保险直赔</option>
                <option value="SELF_PAY">车主自费</option>
              </select>
            </div>
            <div><label>玻璃价格（元）</label><input type="number" min="0" step="0.01" v-model="quoteForm.glass_price"></div>
            <div><label>工时费（元）</label><input type="number" min="0" step="0.01" v-model="quoteForm.labor_fee"></div>
            <div><label>其他费用（元）</label><input type="number" min="0" step="0.01" v-model="quoteForm.other_fee"></div>
            <div v-if="quoteForm.payment_method==='INSURANCE'"><label>保险承担（元）</label>
              <input type="number" min="0" step="0.01" v-model="quoteForm.insurance_amount"></div>
            <div class="full"><label>方案说明（重新说明方案和费用）*</label>
              <textarea rows="2" v-model="quoteForm.note" placeholder="例如：保险拒赔，转为自费方案；或施工中发现型号不符，更换为……"></textarea></div>
          </div>
          <div class="form-actions">
            <button class="btn primary" @click="submitQuote">生成新报价（待车主确认）</button>
            <button class="btn" @click="showQuoteForm=false">取消</button>
          </div>
        </div>
      </div>

      <div class="grid2">
        <div class="card">
          <h3>库存确认</h3>
          <div v-if="wo.inventory.confirmed" class="alert-info">
            已为当前工单预留 <b>{{ wo.inventory.reserved_model }}</b> 一件。
            <span v-if="confirmedQuote && confirmedQuote.glass_model !== wo.inventory.reserved_model" style="color:var(--red)">
              注意：与当前报价型号（{{ confirmedQuote.glass_model }}）不一致，请重新确认。
            </span>
          </div>
          <div v-else class="alert-warn">尚未确认库存。确认库存并预留玻璃后才能安排施工。</div>
          <div class="row mt8" v-if="wo.status!=='DELIVERED'">
            <button class="btn primary" @click="confirmInventory"
              :disabled="!latestQuote || (wo.inventory.confirmed && wo.inventory.reserved_model === latestQuote.glass_model)">
              按当前报价型号确认库存{{ latestQuote ? '（' + latestQuote.glass_model + '）' : '' }}
            </button>
          </div>
          <table class="tbl mt14">
            <thead><tr><th>型号</th><th>名称</th><th>总数</th><th>已预留</th><th>可用</th></tr></thead>
            <tbody>
              <tr v-for="i in inventory" :key="i.glass_model">
                <td class="mono">{{ i.glass_model }}</td><td>{{ i.name }}</td>
                <td>{{ i.total }}</td><td>{{ i.reserved }}</td>
                <td :style="{color: i.available ? 'inherit' : 'var(--red)'}">{{ i.available }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="card">
          <h3>保险理赔</h3>
          <div v-if="confirmedQuote && confirmedQuote.payment_method==='INSURANCE' && wo.status!=='DELIVERED'" class="row">
            <label class="muted">回执延迟(秒)</label>
            <input type="number" min="0" v-model="claimForm.delay_seconds" style="width:80px">
            <label class="muted">模拟结果</label>
            <select v-model="claimForm.force_decision" style="width:110px">
              <option value="">自动(按金额)</option>
              <option value="APPROVED">批复</option>
              <option value="DENIED">拒赔</option>
            </select>
            <button class="btn primary" @click="submitClaim">提交理赔</button>
            <button class="btn" @click="poll">刷新回执</button>
          </div>
          <div v-else-if="!confirmedQuote" class="muted">报价确认后可提交保险理赔。</div>
          <div v-else class="muted">当前方案为车主自费，无需理赔。</div>
          <div v-if="pollResult" class="alert-info mt8">
            拉取 {{ pollResult.fetched }} 条回执：
            <div v-for="r in pollResult.results" :key="r.claim_number">{{ r.claim_number }} → {{ outcomeLabel(r.outcome) }}</div>
          </div>
          <table class="tbl mt14" v-if="wo.claims.length">
            <thead><tr><th>理赔号</th><th>对应方案</th><th>申请金额</th><th>状态</th><th>批复金额</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="c in wo.claims" :key="c.id">
                <td class="mono">{{ c.claim_number }}</td>
                <td>第 {{ c.quote_revision }} 版</td>
                <td>{{ money(c.amount) }}</td>
                <td><span class="badge" :class="CLAIM_STATUS_COLORS[c.status]">{{ c.status_label }}</span>
                  <div v-if="c.decision_reason" class="muted">{{ c.decision_reason }}</div>
                </td>
                <td>{{ c.approved_amount != null ? money(c.approved_amount) : '—' }}</td>
                <td class="muted">提交 {{ fmtDT(c.submitted_at) }}<br>
                  <span v-if="c.decided_at">决定 {{ fmtDT(c.decided_at) }}</span><br>
                  <span v-if="c.received_at">接收 {{ fmtDT(c.received_at) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="muted mt8">尚未提交理赔。</div>
        </div>
      </div>

      <div class="card" v-if="!wo.installation && wo.status!=='DELIVERED'">
        <h3>安排施工</h3>
        <div v-if="startBlockers.length" class="alert-warn">
          暂不能安排施工：<div v-for="b in startBlockers">· {{ b }}</div>
        </div>
        <button class="btn success" :disabled="startBlockers.length" @click="startWork">开始施工</button>
      </div>
    </div>

    <!-- 施工 -->
    <div v-if="tab==='work'">
      <div v-if="!wo.installation" class="card">
        <div class="alert-warn">施工尚未开始。请先在「报价与保险」页完成报价确认、库存确认与保险方案，然后点击「开始施工」。</div>
      </div>
      <template v-else>
        <div class="grid2">
          <div class="card">
            <h3>施工状态</h3>
            <div class="kv">
              <span class="k">开始时间</span><span class="v">{{ fmtDT(wo.installation.started_at) }}</span>
              <span class="k">状态</span>
              <span class="v">
                <span v-if="wo.is_paused" class="badge red">已暂停：{{ wo.pause_reason_label }}</span>
                <span v-else-if="wo.installation.finished_at" class="badge orange">已安装，固化/验收中</span>
                <span v-else class="badge blue">施工中</span>
              </span>
              <template v-if="wo.is_paused">
                <span class="k">暂停说明</span><span class="v">{{ wo.pause_note || '—' }}</span>
              </template>
            </div>
            <div v-if="wo.is_paused" class="alert-warn mt8">
              施工已暂停。请在「报价与保险」页生成新方案报价（说明方案和费用），车主确认后回到此处恢复施工。
            </div>
            <div class="form-actions" v-if="wo.status!=='DELIVERED'">
              <template v-if="!wo.is_paused && !wo.installation.finished_at">
                <select v-model="pauseForm.reason" style="width:150px">
                  <option value="MODEL_MISMATCH">型号不符</option>
                  <option value="NEW_DAMAGE">新发现破损</option>
                  <option value="OTHER">其他</option>
                </select>
                <input v-model="pauseForm.note" placeholder="情况说明" style="width:220px">
                <button class="btn danger" @click="pauseWork">暂停施工</button>
              </template>
              <button v-if="wo.is_paused" class="btn success" @click="resumeWork">恢复施工（需新方案已确认）</button>
            </div>
          </div>

          <div class="card">
            <h3>固化与验收登记</h3>
            <div v-if="curingInfo" class="mt8" :class="curingInfo.ok ? 'alert-info' : 'alert-warn'">
              {{ curingInfo.text }}<span v-if="!curingInfo.ok">，固化时间未到不得交车。</span>
            </div>
            <div v-if="wo.installation.finished_at" class="muted mt8">
              胶型：{{ wo.installation.glue_type || '—' }} ｜ 完成于 {{ fmtDT(wo.installation.finished_at) }}
            </div>
            <div v-if="wo.status!=='DELIVERED' && !wo.is_paused">
              <div class="form-grid mt8" style="grid-template-columns:1fr 1fr">
                <div><label>胶类型</label><input v-model="finishForm.glue_type"></div>
                <div><label>固化截止时间</label><input type="datetime-local" v-model="finishForm.curing"></div>
              </div>
              <div class="form-actions">
                <button class="btn primary" @click="finishWork">{{ wo.installation.finished_at ? '重新登记安装完成（验收将重置）' : '登记安装完成' }}</button>
              </div>
              <div v-if="wo.installation.finished_at" style="border-top:1px dashed var(--border);margin-top:12px;padding-top:10px">
                <div class="row">
                  <label><input type="radio" value="PASSED" v-model="acceptForm.result" style="width:auto"> 验收通过</label>
                  <label><input type="radio" value="FAILED" v-model="acceptForm.result" style="width:auto"> 验收不通过</label>
                  <input v-model="acceptForm.note" placeholder="验收备注" style="flex:1;min-width:160px">
                  <button class="btn primary" @click="submitAcceptance">登记验收结果</button>
                </div>
              </div>
            </div>
            <div class="mt8">
              当前验收结果：
              <span v-if="wo.installation.acceptance_result==='PASSED'" class="badge green">通过</span>
              <span v-else-if="wo.installation.acceptance_result==='FAILED'" class="badge red">未通过</span>
              <span v-else class="badge gray">未验收</span>
              <span class="muted">{{ wo.installation.acceptance_note }}</span>
            </div>
          </div>
        </div>

        <div class="card">
          <h3>安装照片（{{ wo.photos.length }} 张）</h3>
          <div class="row" v-if="wo.status!=='DELIVERED'">
            <select v-model="photoStage" style="width:120px">
              <option value="BEFORE">施工前</option>
              <option value="DURING">施工中</option>
              <option value="AFTER">施工后</option>
            </select>
            <input type="file" accept="image/*" ref="fileInput" style="width:auto">
            <button class="btn primary" @click="uploadPhoto">上传照片</button>
          </div>
          <div class="gallery mt14" v-if="wo.photos.length">
            <div class="ph" v-for="p in wo.photos" :key="p.id">
              <a :href="p.url" target="_blank"><img :src="p.url" :alt="p.stage_label"></a>
              <div class="meta">{{ p.stage_label }} · {{ fmtDT(p.uploaded_at) }}</div>
            </div>
          </div>
          <div v-else class="muted mt8">尚未上传照片。交车前必须至少上传一张安装照片。</div>
        </div>
      </template>
    </div>

    <!-- 交车 -->
    <div v-if="tab==='delivery'">
      <div v-if="wo.delivery.delivered" class="banner done">✔ 本工单已于 {{ fmtDT(wo.delivery.delivered_at) }} 交付，工单已关闭。</div>
      <div v-else-if="wo.delivery.deliverable" class="banner ok">✅ 当前允许交付：全部交付条件均已满足。</div>
      <div v-else class="banner no">⛔ 当前不允许交付：以下条件未满足，请逐项处理。</div>

      <div class="card">
        <h3>交付条件检查</h3>
        <div class="check-row" v-for="c in wo.delivery.checks" :key="c.key">
          <span class="icon" :class="c.passed ? 'ok' : 'no'">{{ c.passed ? '✓' : '✗' }}</span>
          <div>
            <div class="label">{{ c.label }}</div>
            <div class="detail">{{ c.detail }}</div>
          </div>
        </div>
        <div class="form-actions" v-if="!wo.delivery.delivered">
          <button class="btn success" :disabled="!wo.delivery.deliverable" @click="deliver">确认交车</button>
          <button class="btn" @click="load()">重新检查</button>
          <span class="muted">固化时间未到或验收未通过时，系统禁止交车（服务端强制校验）。</span>
        </div>
      </div>
    </div>
  </div>
  <div v-else>
    <div v-if="error" class="alert-error">{{ error }}</div>
    <div v-else class="muted">加载中…</div>
  </div>`,
};

/* ---------------- 车主页 ---------------- */
const OwnerView = {
  props: ['token'],
  data() { return { wo: null, error: '', timer: null }; },
  computed: {
    pendingQuotes() {
      return this.wo ? this.wo.quotes.filter(q => q.status === 'PENDING_OWNER') : [];
    },
  },
  async mounted() {
    await this.load();
    this.timer = setInterval(() => { if (!document.hidden) this.load(); }, 6000);
  },
  unmounted() { clearInterval(this.timer); },
  methods: {
    async load() {
      try { this.wo = await api('/api/owner/' + this.token); this.error = ''; }
      catch (e) { this.error = e.message; }
    },
    async confirm(q) {
      if (!confirm('确认第 ' + q.revision + ' 版报价方案？确认即授权门店按此方案施工与收费。')) return;
      try {
        this.wo = await api('/api/owner/' + this.token + '/quotes/' + q.id + '/confirm', { method: 'POST' });
        notify('已确认授权，感谢！');
      } catch (e) { alert(e.message); }
    },
  },
  template: `
  <div v-if="wo">
    <div class="page-head"><h2>车主服务进度</h2><span class="badge" :class="STATUS_COLORS[wo.status] || 'gray'">{{ wo.status_label }}</span></div>

    <div v-if="pendingQuotes.length" class="card" style="border-color:var(--orange)">
      <h3 style="border-left-color:var(--orange)">待您确认的报价方案</h3>
      <div v-for="q in pendingQuotes" :key="q.id" class="mt8">
        <div class="alert-warn">
          <b>第 {{ q.revision }} 版（{{ q.reason_label }}）</b>：{{ q.note }}
        </div>
        <div class="big-amounts mt8">
          <div class="item"><div class="num">{{ q.glass_model }}</div><div class="lbl">玻璃型号</div></div>
          <div class="item"><div class="num">{{ money(q.total) }}</div><div class="lbl">总价</div></div>
          <div class="item"><div class="num">{{ money(q.insurance_amount) }}</div><div class="lbl">保险承担</div></div>
          <div class="item"><div class="num" style="color:var(--orange)">{{ money(q.self_pay_amount) }}</div><div class="lbl">您需自付</div></div>
        </div>
        <div class="muted mt8">支付方式：{{ q.payment_label }} ｜ 玻璃 {{ money(q.glass_price) }} + 工时 {{ money(q.labor_fee) }} + 其他 {{ money(q.other_fee) }}</div>
        <div class="form-actions">
          <button class="btn primary" @click="confirm(q)">确认此报价（授权）</button>
          <span class="muted">确认后门店才会继续施工 / 提交保险</span>
        </div>
      </div>
    </div>

    <div class="grid2">
      <div class="card">
        <h3>车辆与玻璃</h3>
        <div class="kv">
          <span class="k">工单号</span><span class="v mono">{{ wo.order_no }}</span>
          <span class="k">车牌</span><span class="v">{{ wo.plate_number }}</span>
          <span class="k">车型</span><span class="v">{{ wo.vehicle_model || '—' }}</span>
          <span class="k">玻璃型号</span><span class="v"><b>{{ wo.glass_model || '—' }}</b></span>
          <span class="k">预计提车</span><span class="v">{{ fmtDT(wo.estimated_pickup_at) }}</span>
          <span class="k" v-if="wo.delivered_at">交付时间</span><span class="v" v-if="wo.delivered_at">{{ fmtDT(wo.delivered_at) }}</span>
        </div>
      </div>
      <div class="card">
        <h3>费用</h3>
        <template v-if="wo.current_quote">
          <div class="big-amounts">
            <div class="item"><div class="num">{{ money(wo.current_quote.total) }}</div><div class="lbl">总价</div></div>
            <div class="item"><div class="num">{{ money(wo.current_quote.insurance_amount) }}</div><div class="lbl">保险承担</div></div>
            <div class="item"><div class="num" style="color:var(--orange)">{{ money(wo.current_quote.self_pay_amount) }}</div><div class="lbl">您需自付</div></div>
          </div>
          <div class="mt8 muted">{{ wo.insurance_detail }}</div>
        </template>
        <div v-else class="muted">报价确认后展示费用明细。</div>
      </div>
    </div>

    <div class="card">
      <h3>报价记录</h3>
      <table class="tbl">
        <thead><tr><th>版本</th><th>原因</th><th>总价</th><th>保险承担</th><th>自付</th><th>状态</th><th>说明</th></tr></thead>
        <tbody>
          <tr v-for="q in wo.quotes" :key="q.id">
            <td>第 {{ q.revision }} 版</td><td>{{ q.reason_label }}</td>
            <td>{{ money(q.total) }}</td><td>{{ money(q.insurance_amount) }}</td><td>{{ money(q.self_pay_amount) }}</td>
            <td><span class="badge" :class="QUOTE_STATUS_COLORS[q.status]">{{ q.status_label }}</span></td>
            <td class="muted">{{ q.note }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h3>进度动态</h3>
      <ul class="timeline">
        <li v-for="e in wo.events" :key="e.id">
          <div>{{ e.message }}</div>
          <div class="t">{{ fmtDT(e.created_at) }}</div>
        </li>
      </ul>
    </div>
  </div>
  <div v-else>
    <div v-if="error" class="alert-error">{{ error }}</div>
    <div v-else class="muted">加载中…</div>
  </div>`,
};

/* ---------------- 根组件与路由 ---------------- */
function parseRoute() {
  const h = location.hash || '#/';
  let m;
  if (h === '#/new') return { name: 'new' };
  if ((m = h.match(/^#\/wo\/(\d+)/))) return { name: 'detail', id: m[1] };
  if ((m = h.match(/^#\/owner\/([0-9a-f]+)/))) return { name: 'owner', token: m[1] };
  return { name: 'list' };
}

const Root = {
  components: { ListView, NewView, DetailView, OwnerView },
  data() { return { route: parseRoute(), bus }; },
  computed: {
    currentComp() {
      return { list: 'ListView', new: 'NewView', detail: 'DetailView', owner: 'OwnerView' }[this.route.name];
    },
    currentProps() {
      if (this.route.name === 'detail') return { id: this.route.id, key: this.route.id };
      if (this.route.name === 'owner') return { token: this.route.token, key: this.route.token };
      return {};
    },
  },
  mounted() {
    window.addEventListener('hashchange', () => { this.route = parseRoute(); });
  },
  template: `
  <div>
    <div class="topnav">
      <a class="brand" href="#/">🚗 汽车玻璃保险直赔与安装验收系统</a>
      <a href="#/">工单列表</a>
      <a href="#/new">新建工单</a>
      <div class="spacer"></div>
      <span class="hint">模拟保险接口文档：<a href="/mock-insurance/docs" target="_blank" style="color:#8fa3c8">/mock-insurance/docs</a></span>
    </div>
    <div class="container">
      <component :is="currentComp" v-bind="currentProps"></component>
    </div>
    <div v-if="bus.msg" class="toast">{{ bus.msg }}</div>
  </div>`,
};

createApp(Root).mount('#app');

// Runs Code.gs and Logic.gs together, as Apps Script does, against a small in-memory
// stand-in for the Google services they use. Checks the wiring: row and column numbers,
// what gets written where, and which emails and triggers are created.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const HEADERS = ['Job ID', 'Created', 'Customer', 'Phone', 'Address', 'Job type', 'Description',
  'Engineer', 'Status', 'Value £', 'Scheduled', 'Quoted on', 'Completed on', 'Invoiced on',
  'Paid on', 'Notes'];
const col = (name) => HEADERS.indexOf(name) + 1;
const iso = (d) => d.toISOString().slice(0, 10);

class FakeSheet {
  constructor(name, rows) {
    this.name = name;
    this.rows = rows.map((r) => r.slice());
    this.formats = {};
  }
  getName() { return this.name; }
  getLastRow() {
    for (let r = this.rows.length; r > 0; r--) {
      if (this.rows[r - 1].some((v) => v !== '')) return r;
    }
    return 0;
  }
  getLastColumn() { return Math.max(...this.rows.map((r) => r.length)); }
  getMaxRows() { return 1000; }
  insertRowsAfter() {}
  getDataRange() { return this.getRange(1, 1, this.getLastRow(), this.getLastColumn()); }
  getRange(row, column, numRows = 1, numColumns = 1) {
    return new FakeRange(this, row, column, numRows, numColumns);
  }
  getRangeList(a1s) {
    const sheet = this;
    return { setNumberFormat(f) { a1s.forEach((a1) => { sheet.formats[a1] = f; }); } };
  }
  cell(row, column) { return (this.rows[row - 1] || [])[column - 1] ?? ''; }
  put(row, column, value) {
    while (this.rows.length < row) this.rows.push([]);
    const r = this.rows[row - 1];
    while (r.length < column) r.push('');
    r[column - 1] = value;
  }
}

class FakeRange {
  constructor(sheet, row, column, numRows, numColumns) {
    Object.assign(this, { sheet, row, column, numRows, numColumns });
  }
  getSheet() { return this.sheet; }
  getRow() { return this.row; }
  getColumn() { return this.column; }
  getLastRow() { return this.row + this.numRows - 1; }
  getLastColumn() { return this.column + this.numColumns - 1; }
  getA1Notation() { return String.fromCharCode(64 + this.column) + this.row; }
  getValues() {
    return Array.from({ length: this.numRows }, (_, i) =>
      Array.from({ length: this.numColumns }, (_, j) => this.sheet.cell(this.row + i, this.column + j)));
  }
  setValue(v) { this.sheet.put(this.row, this.column, v); }
  setValues(values) {
    assert.equal(values.length, this.numRows);
    values.forEach((r, i) => {
      assert.equal(r.length, this.numColumns);
      r.forEach((v, j) => this.sheet.put(this.row + i, this.column + j, v));
    });
  }
}

function load() {
  const jobs = new FakeSheet('Jobs', [
    HEADERS,
    ['J-1001', new Date('2026-10-01'), 'Ann Lee', '07700 900111', '1 A St', 'Radiators', '',
      'Tom', 'Booked', 300, new Date('2026-10-02'), new Date('2026-10-01'), '', '', '', ''],
    ['J-1002', new Date('2026-10-05'), 'Bo Chan', '07700 900222', '2 B St', 'Boiler service', '',
      'Sam', 'Done', 95, new Date('2026-10-06'), new Date('2026-10-05'), new Date('2026-10-06'),
      '', '', ''],
  ]);
  const lists = new FakeSheet('Lists', [
    ['Status', 'Job type', 'Engineer'],
    ['Enquiry', 'Radiators', 'Sam'], ['Quoted', 'Boiler service', 'Tom'], ['Invoiced', '', ''],
  ]);
  const settings = new FakeSheet('Settings', [
    ['Setting', 'Value', 'What it does'], ['Business name', 'Test Plumbing', ''],
    ['Summary email to', '', ''], ['Chase quotes after (days)', 7, ''],
    ['Flag unpaid after (days)', 30, ''],
  ]);
  const tabs = { Jobs: jobs, Lists: lists, Settings: settings };
  const sent = [];
  const triggers = [];
  const alerts = [];
  const spreadsheet = {
    getSheetByName: (n) => tabs[n] || null,
    getSpreadsheetTimeZone: () => 'Etc/UTC',
    getName: () => 'Sheet name',
    toast: () => {},
  };
  const context = {
    SpreadsheetApp: { getActive: () => spreadsheet, getUi: () => ({ alert: (m) => alerts.push(m) }) },
    Utilities: { formatDate: (d) => iso(d) },
    LockService: { getDocumentLock: () => ({ waitLock() {}, releaseLock() {} }) },
    MailApp: { sendEmail: (m) => sent.push(m) },
    Session: { getEffectiveUser: () => ({ getEmail: () => 'owner@example.com' }) },
    ScriptApp: {
      WeekDay: { MONDAY: 'MONDAY' },
      getProjectTriggers: () => triggers.slice(),
      deleteTrigger: (t) => triggers.splice(triggers.indexOf(t), 1),
      newTrigger: (fn) => ({ timeBased: () => ({ onWeekDay: (day) => ({ atHour: (h) => ({
        create: () => triggers.push({ getHandlerFunction: () => fn, day, h }),
      }) }) }) }),
    },
  };
  vm.createContext(context);
  for (const file of ['Logic.gs', 'Code.gs']) {  // one shared global scope, like Apps Script
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'apps-script', file), 'utf8'),
      context, { filename: file });
  }
  return { context, jobs, settings, sent, triggers, alerts, today: iso(new Date()) };
}

test('changing a status by hand stamps the date', () => {
  const { context, jobs, today } = load();
  jobs.put(3, col('Status'), 'Invoiced');
  context.onEdit({ range: jobs.getRange(3, col('Status')) });
  assert.equal(jobs.cell(3, col('Invoiced on')), today);
  assert.equal(jobs.cell(2, col('Invoiced on')), '');
});

test('typing a customer on a new row gives it the next job number', () => {
  const { context, jobs, today } = load();
  jobs.put(4, col('Customer'), 'Cara Doyle');
  context.onEdit({ range: jobs.getRange(4, col('Customer')) });
  assert.equal(jobs.cell(4, col('Job ID')), 'J-1003');
  assert.equal(jobs.cell(4, col('Created')), today);
});

test('edits on other tabs are ignored', () => {
  const { context, settings } = load();
  settings.put(2, 2, 'New name');
  context.onEdit({ range: settings.getRange(2, 2) });
  assert.equal(settings.cell(2, 1), 'Business name');
});

test('the form adds a full row under the last job', () => {
  const { context, jobs, today } = load();
  const id = context.addJob({ 'Customer': 'Dee Ellis', 'Phone': '07700 900333',
    'Job type': 'Radiators', 'Status': 'Quoted', 'Value £': '640', 'Scheduled': '' });
  assert.equal(id, 'J-1003');
  assert.equal(jobs.cell(4, col('Job ID')), 'J-1003');
  assert.equal(jobs.cell(4, col('Customer')), 'Dee Ellis');
  assert.equal(jobs.cell(4, col('Quoted on')), today);
  assert.equal(jobs.cell(4, col('Value £')), 640);
  assert.equal(jobs.formats.D4, '@'); // phone stays text
});

test('the form rejects bad input with a readable message', () => {
  const { context, jobs } = load();
  assert.throws(() => context.addJob({ 'Customer': '', 'Status': 'Paid' }),
    /Customer is required\. Status must be one of: Enquiry, Quoted, Invoiced\./);
  assert.equal(jobs.getLastRow(), 3);
});

test('the summary email goes to the owner when no address is set', () => {
  const { context, sent } = load();
  context.sendWeeklySummary();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].to, 'owner@example.com');
  assert.equal(sent[0].name, 'Test Plumbing');
  assert.match(sent[0].subject, /^Test Plumbing: \d+ jobs this week, £0 unpaid$/);
  assert.match(sent[0].htmlBody, /Booked for the next 7 days/);
});

test('the summary email uses the address on the Settings tab', () => {
  const { context, settings, sent } = load();
  settings.put(3, 2, 'office@example.com');
  context.sendWeeklySummary();
  assert.equal(sent[0].to, 'office@example.com');
});

test('turning the Monday email on twice still leaves one trigger', () => {
  const { context, triggers, alerts } = load();
  context.turnOnWeeklySummary();
  context.turnOnWeeklySummary();
  assert.equal(triggers.length, 1);
  assert.equal(triggers[0].day, 'MONDAY');
  assert.equal(triggers[0].h, 7);
  context.turnOffWeeklySummary();
  assert.equal(triggers.length, 0);
  assert.match(alerts.at(-1), /off/);
});

test('the form dropdowns come from the Lists tab', () => {
  const { context } = load();
  assert.deepEqual(JSON.parse(JSON.stringify(context.formOptions_())), {
    statuses: ['Enquiry', 'Quoted', 'Invoiced'],
    jobTypes: ['Radiators', 'Boiler service'],
    engineers: ['Sam', 'Tom'],
  });
});

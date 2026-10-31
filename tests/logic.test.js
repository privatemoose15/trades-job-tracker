// Tests for apps-script/Logic.gs. Run with: npm test (or node --test tests/)
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const L = require(path.join(__dirname, '..', 'apps-script', 'Logic.gs'));

const HEADERS = ['Job ID', 'Created', 'Customer', 'Phone', 'Address', 'Job type', 'Description',
  'Engineer', 'Status', 'Value £', 'Scheduled', 'Quoted on', 'Completed on', 'Invoiced on',
  'Paid on', 'Notes'];
const TODAY = '2026-11-02'; // a Monday
const col = (name) => HEADERS.indexOf(name) + 1;

function row(values) {
  return HEADERS.map((h) => (h in values ? values[h] : ''));
}

test('status changes stamp the right date column', () => {
  assert.equal(L.stampColumnFor('Quoted'), 'Quoted on');
  assert.equal(L.stampColumnFor(' Paid '), 'Paid on');
  assert.equal(L.stampColumnFor('Booked'), null);
  assert.equal(L.stampColumnFor(''), null);
});

test('job numbers continue from the highest one used', () => {
  assert.equal(L.nextJobId([]), 'J-1001');
  assert.equal(L.nextJobId(['J-1001', 'J-1030', 'J-1002', '', 'junk', 'J-12x']), 'J-1031');
});

test('editing Status fills in its date once and never overwrites it', () => {
  const rows = [
    row({ 'Job ID': 'J-1001', 'Status': 'Quoted' }),
    row({ 'Job ID': 'J-1002', 'Status': 'Paid', 'Paid on': '2026-10-01' }),
    row({ 'Job ID': 'J-1003', 'Status': 'Booked' }),
  ];
  const writes = L.planEdits(HEADERS, rows, 5, col('Status'), col('Status'), TODAY, []);
  assert.deepEqual(writes, [{ row: 5, col: col('Quoted on'), value: TODAY }]);
});

test('typing a customer on an empty row numbers the job and dates it', () => {
  const rows = [row({ 'Customer': 'New Person' }), row({ 'Customer': 'Second Person' })];
  const writes = L.planEdits(HEADERS, rows, 31, 1, HEADERS.length, TODAY, ['J-1030']);
  assert.deepEqual(writes, [
    { row: 31, col: col('Job ID'), value: 'J-1031' },
    { row: 31, col: col('Created'), value: TODAY },
    { row: 32, col: col('Job ID'), value: 'J-1032' },
    { row: 32, col: col('Created'), value: TODAY },
  ]);
});

test('edits elsewhere, and the header row, change nothing', () => {
  const rows = [row({ 'Job ID': 'J-1001', 'Customer': 'A', 'Status': 'Quoted' })];
  assert.deepEqual(L.planEdits(HEADERS, rows, 2, col('Notes'), col('Notes'), TODAY, []), []);
  assert.deepEqual(L.planEdits(HEADERS, [HEADERS], 1, 1, HEADERS.length, TODAY, []), []);
});

test('columns are found by name, so a moved column still works', () => {
  const moved = ['Customer', 'Status', 'Notes', 'Quoted on', 'Job ID', 'Created'];
  const writes = L.planEdits(moved, [['A', 'Quoted', '', '', '', '']], 2, 1, 2, TODAY, []);
  assert.deepEqual(writes, [
    { row: 2, col: 4, value: TODAY },
    { row: 2, col: 5, value: 'J-1001' },
    { row: 2, col: 6, value: TODAY },
  ]);
});

function job(values) {
  return Object.assign({ 'Value £': 0 }, values);
}

const JOBS = [
  job({ 'Job ID': 'J-1', 'Status': 'Enquiry' }),
  job({ 'Job ID': 'J-2', 'Status': 'Quoted', 'Quoted on': '2026-10-20', 'Value £': 900 }),
  job({ 'Job ID': 'J-3', 'Status': 'Quoted', 'Quoted on': '2026-10-31', 'Value £': 100 }),
  job({ 'Job ID': 'J-4', 'Status': 'Quoted', 'Quoted on': '2026-10-26', 'Value £': 50 }),
  job({ 'Job ID': 'J-5', 'Status': 'Booked', 'Scheduled': '2026-11-05', 'Value £': 300 }),
  job({ 'Job ID': 'J-6', 'Status': 'Booked', 'Scheduled': '2026-11-02', 'Value £': 95 }),
  job({ 'Job ID': 'J-7', 'Status': 'Booked', 'Scheduled': '2026-11-09', 'Value £': 4000 }),
  job({ 'Job ID': 'J-8', 'Status': 'Booked', 'Scheduled': '2026-10-30', 'Value £': 120 }),
  job({ 'Job ID': 'J-9', 'Status': 'Invoiced', 'Invoiced on': '2026-09-20', 'Value £': 980 }),
  job({ 'Job ID': 'J-10', 'Status': 'Invoiced', 'Invoiced on': '2026-10-25', 'Value £': 95 }),
  job({ 'Job ID': 'J-11', 'Status': 'Paid', 'Paid on': '2026-11-01', 'Value £': 150 }),
  job({ 'Job ID': 'J-12', 'Status': 'Paid', 'Paid on': '2026-10-31', 'Value £': 2650 }),
];

test('weekly summary picks the right jobs in date order', () => {
  const s = L.buildSummary(JOBS, TODAY, { chaseDays: 7, unpaidDays: 30 });
  const ids = (list) => list.map((j) => j['Job ID']);
  assert.deepEqual(ids(s.nextWeek), ['J-6', 'J-5']); // J-7 is 7 days out: next week's email
  assert.equal(s.nextWeekValue, 395);
  assert.deepEqual(ids(s.datePassed), ['J-8']);
  assert.deepEqual(ids(s.chase), ['J-2', 'J-4']); // 13 and 7 days; J-3 is only 2 days old
  assert.deepEqual(s.chase.map((j) => j.days), [13, 7]);
  assert.deepEqual(ids(s.unpaid), ['J-9', 'J-10']);
  assert.deepEqual(s.unpaid.map((j) => j.late), [true, false]);
  assert.equal(s.unpaidValue, 1075);
  assert.equal(s.paidThisMonth, 150); // October's payment doesn't count in November
  assert.equal(s.enquiries, 1);
  assert.equal(s.quotesOut, 3);
});

test('summary settings change the chase and late thresholds', () => {
  const s = L.buildSummary(JOBS, TODAY, { chaseDays: 14, unpaidDays: 5 });
  assert.deepEqual(s.chase.map((j) => j['Job ID']), []);
  assert.deepEqual(s.unpaid.map((j) => j.late), [true, true]);
});

test('summary email escapes anything typed into the sheet', () => {
  const nasty = job({ 'Job ID': 'J-1', 'Status': 'Booked', 'Scheduled': TODAY,
    'Customer': '<script>alert(1)</script>', 'Address': 'O\'Brien & Sons' });
  const s = L.buildSummary([nasty], TODAY, {});
  const html = L.summaryHtml(s, 'Test & Co');
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('O&#39;Brien &amp; Sons'));
  assert.ok(html.includes('Test &amp; Co'));
  assert.ok(html.includes('Mon 2 Nov'));
  assert.equal(L.summarySubject(s, 'Test & Co'), 'Test & Co: 1 jobs this week, £0 unpaid');
});

test('summary email handles an empty sheet', () => {
  const html = L.summaryHtml(L.buildSummary([], TODAY, {}), 'Empty Ltd');
  assert.ok(html.includes('Nothing booked yet.'));
  assert.ok(html.includes('All invoices are paid.'));
  assert.ok(!html.includes('date has passed'));
});

test('money and dates are formatted for UK readers', () => {
  assert.equal(L.money(1234567.4), '£1,234,567');
  assert.equal(L.money(''), '£0');
  assert.equal(L.shortDate('2026-12-25'), 'Fri 25 Dec');
  assert.equal(L.shortDate(''), '');
});

const OPTIONS = { statuses: ['Enquiry', 'Quoted'], jobTypes: ['Radiators'], engineers: ['Sam'] };

test('the add-a-job form is checked and tidied', () => {
  const ok = L.cleanJob({ 'Customer': '  Ann Lee ', 'Value £': '£1,250', 'Status': 'Quoted',
    'Job type': 'Radiators', 'Scheduled': '2026-11-12' }, OPTIONS);
  assert.deepEqual(ok.errors, []);
  assert.equal(ok.job['Customer'], 'Ann Lee');
  assert.equal(ok.job['Value £'], 1250);

  const bad = L.cleanJob({ 'Customer': ' ', 'Value £': 'lots', 'Status': 'Done',
    'Engineer': 'Bob', 'Scheduled': 'tuesday' }, OPTIONS);
  assert.deepEqual(bad.errors, [
    'Customer is required.',
    'Status must be one of: Enquiry, Quoted.',
    'Engineer must be one of: Sam.',
    'Value must be a number of pounds, e.g. 250.',
    'Scheduled must be a date.',
  ]);
  assert.equal(L.cleanJob({ 'Customer': 'X' }, OPTIONS).job['Status'], 'Enquiry');
});

test('a new row lines up with the columns and is safe from formulas', () => {
  const { job: j } = L.cleanJob({ 'Customer': '=IMPORTXML("http://x")', 'Phone': '+44 7700 900111',
    'Status': 'Quoted', 'Value £': '640' }, OPTIONS);
  const r = L.jobToRow(HEADERS, j, 'J-1031', TODAY);
  assert.equal(r.length, HEADERS.length);
  assert.equal(r[col('Job ID') - 1], 'J-1031');
  assert.equal(r[col('Created') - 1], TODAY);
  assert.equal(r[col('Quoted on') - 1], TODAY);
  assert.equal(r[col('Paid on') - 1], '');
  assert.equal(r[col('Customer') - 1], '\'=IMPORTXML("http://x")');
  assert.equal(r[col('Phone') - 1], '\'+44 7700 900111');
  assert.equal(r[col('Value £') - 1], 640);
});

test('rows without a job number or customer are ignored', () => {
  const jobs = L.rowsToJobs(HEADERS, [row({ 'Job ID': 'J-1' }), row({}), row({ 'Customer': 'B' })]);
  assert.equal(jobs.length, 2);
  assert.equal(jobs[0]['Job ID'], 'J-1');
});

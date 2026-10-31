/**
 * @OnlyCurrentDoc
 * Job tracker for a small trades business: the menu, the "Add a job" form, automatic dates
 * and the Monday summary email. The rules themselves are in Logic.gs.
 * The OnlyCurrentDoc tag above limits the script to this one spreadsheet.
 */

const JOBS_TAB = 'Jobs';
const TEXT_COLUMNS = ['Job ID', 'Customer', 'Phone', 'Address', 'Description', 'Notes'];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Job tracker')
    .addItem('Add a job…', 'showNewJobDialog')
    .addSeparator()
    .addItem('Email me the summary now', 'sendWeeklySummary')
    .addItem('Turn on Monday summary email', 'turnOnWeeklySummary')
    .addItem('Turn off Monday summary email', 'turnOffWeeklySummary')
    .addToUi();
}

/** Runs on every hand edit: stamps dates when Status changes and numbers new jobs. */
function onEdit(e) {
  const range = e.range;
  const sheet = range.getSheet();
  if (sheet.getName() !== JOBS_TAB || range.getLastRow() < 2) return;

  const headers = headersOf_(sheet);
  const firstRow = Math.max(range.getRow(), 2);
  const rows = sheet.getRange(firstRow, 1, range.getLastRow() - firstRow + 1, headers.length)
    .getValues();
  const customerCol = headers.indexOf('Customer') + 1;
  const ids = customerCol >= range.getColumn() && customerCol <= range.getLastColumn()
    ? jobIds_(sheet, headers) : [];

  planEdits(headers, rows, firstRow, range.getColumn(), range.getLastColumn(), today_(), ids)
    .forEach(function (w) { sheet.getRange(w.row, w.col).setValue(w.value); });
}

function showNewJobDialog() {
  const page = HtmlService.createTemplateFromFile('NewJob');
  page.options = formOptions_();
  SpreadsheetApp.getUi().showModalDialog(page.evaluate().setWidth(460).setHeight(620), 'Add a job');
}

/** Called by the form. Returns the new job number, or throws a message the form shows. */
function addJob(form) {
  const checked = cleanJob(form, formOptions_());
  if (checked.errors.length) throw new Error(checked.errors.join(' '));

  const lock = LockService.getDocumentLock(); // two people saving at once get different numbers
  lock.waitLock(10000);
  try {
    const sheet = jobsSheet_();
    const headers = headersOf_(sheet);
    const id = nextJobId(jobIds_(sheet, headers));
    const row = sheet.getLastRow() + 1;
    if (row > sheet.getMaxRows()) sheet.insertRowsAfter(sheet.getMaxRows(), 100);

    // Plain-text format first, so "3/4 inch pipe" or a phone number isn't turned into a date
    const textCells = TEXT_COLUMNS
      .map(function (name) { return headers.indexOf(name) + 1; })
      .filter(function (c) { return c > 0; })
      .map(function (c) { return sheet.getRange(row, c).getA1Notation(); });
    if (textCells.length) sheet.getRangeList(textCells).setNumberFormat('@');

    sheet.getRange(row, 1, 1, headers.length)
      .setValues([jobToRow(headers, checked.job, id, today_())]);
    return id;
  } finally {
    lock.releaseLock();
  }
}

function sendWeeklySummary() {
  const settings = readSettings_();
  const to = settings.emailTo || Session.getEffectiveUser().getEmail();
  const summary = buildSummary(readJobs_(), today_(), settings);
  MailApp.sendEmail({
    to: to,
    subject: summarySubject(summary, settings.businessName),
    htmlBody: summaryHtml(summary, settings.businessName),
    name: settings.businessName,
  });
  toast_('Summary sent to ' + to);
}

function turnOnWeeklySummary() {
  removeSummaryTriggers_();
  ScriptApp.newTrigger('sendWeeklySummary')
    .timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(7).create();
  const to = readSettings_().emailTo || Session.getEffectiveUser().getEmail();
  SpreadsheetApp.getUi().alert('Monday summary is on. It goes to ' + to +
    ' every Monday between 7 and 8am.');
}

function turnOffWeeklySummary() {
  const removed = removeSummaryTriggers_();
  SpreadsheetApp.getUi().alert(removed ? 'Monday summary is off.' : 'Monday summary was not on.');
}

// --- helpers ---

function jobsSheet_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName(JOBS_TAB);
  if (!sheet) throw new Error('There is no tab called "' + JOBS_TAB + '".');
  return sheet;
}

function headersOf_(sheet) {
  return sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0]
    .map(function (h) { return String(h).trim(); });
}

function jobIds_(sheet, headers) {
  const col = headers.indexOf('Job ID') + 1;
  const last = sheet.getLastRow();
  if (!col || last < 2) return [];
  return sheet.getRange(2, col, last - 1, 1).getValues().map(function (r) { return r[0]; });
}

/** Today in the spreadsheet's own time zone, as yyyy-mm-dd. */
function today_() {
  return Utilities.formatDate(new Date(), SpreadsheetApp.getActive().getSpreadsheetTimeZone(),
    'yyyy-MM-dd');
}

function readJobs_() {
  const values = jobsSheet_().getDataRange().getValues();
  const tz = SpreadsheetApp.getActive().getSpreadsheetTimeZone();
  const rows = values.slice(1).map(function (row) {
    return row.map(function (v) {
      return v instanceof Date ? Utilities.formatDate(v, tz, 'yyyy-MM-dd') : v;
    });
  });
  return rowsToJobs(values[0].map(function (h) { return String(h).trim(); }), rows);
}

function readSettings_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName('Settings');
  const map = {};
  if (sheet) {
    sheet.getDataRange().getValues().forEach(function (r) { map[String(r[0]).trim()] = r[1]; });
  }
  return {
    businessName: String(map['Business name'] || SpreadsheetApp.getActive().getName()),
    emailTo: String(map['Summary email to'] || '').trim(),
    chaseDays: Number(map['Chase quotes after (days)']) || 7,
    unpaidDays: Number(map['Flag unpaid after (days)']) || 30,
  };
}

/** Dropdown choices for the form, read from the Lists tab. */
function formOptions_() {
  const sheet = SpreadsheetApp.getActive().getSheetByName('Lists');
  const values = sheet ? sheet.getDataRange().getValues() : [[]];
  const column = function (name) {
    const c = values[0].indexOf(name);
    if (c < 0) return [];
    return values.slice(1).map(function (r) { return String(r[c]).trim(); }).filter(String);
  };
  return { statuses: column('Status'), jobTypes: column('Job type'), engineers: column('Engineer') };
}

function removeSummaryTriggers_() {
  let removed = 0;
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'sendWeeklySummary') {
      ScriptApp.deleteTrigger(t);
      removed++;
    }
  });
  return removed;
}

function toast_(message) {
  try {
    SpreadsheetApp.getActive().toast(message, 'Job tracker', 5);
  } catch (err) {
    // No spreadsheet window when the Monday trigger runs: nothing to show
  }
}

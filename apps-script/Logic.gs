/**
 * Job tracker rules, with no Google services in here so they can be tested with Node
 * (see tests/logic.test.js). Dates are passed around as 'yyyy-mm-dd' strings.
 */

/** Moving a job to one of these statuses fills in the matching date column, once. */
const STAMP_COLUMNS = {
  'Quoted': 'Quoted on',
  'Done': 'Completed on',
  'Invoiced': 'Invoiced on',
  'Paid': 'Paid on',
};

function stampColumnFor(status) {
  return STAMP_COLUMNS[String(status || '').trim()] || null;
}

function isBlank(value) {
  return value === '' || value === null || value === undefined;
}

/** Next job number after the highest J-#### already used (J-1001 for an empty sheet). */
function nextJobId(ids) {
  let max = 1000;
  ids.forEach(function (id) {
    const m = /^J-(\d+)$/.exec(String(id).trim());
    if (m) max = Math.max(max, Number(m[1]));
  });
  return 'J-' + (max + 1);
}

/**
 * What to fill in after someone edits the Jobs tab by hand.
 * rows: the edited rows (whole rows), starting at sheet row firstRow.
 * colFrom/colTo: the edited columns (1-based). existingIds: every Job ID already on the tab.
 * Returns the cells to write as [{row, col, value}], 1-based.
 */
function planEdits(headers, rows, firstRow, colFrom, colTo, todayIso, existingIds) {
  const col = function (name) { return headers.indexOf(name); };
  const edited = function (name) {
    const c = col(name) + 1;
    return c > 0 && c >= colFrom && c <= colTo;
  };
  const ids = existingIds.slice();
  const writes = [];

  rows.forEach(function (row, i) {
    const r = firstRow + i;
    if (r < 2) return; // header row

    if (edited('Status')) {
      const stamp = col(stampColumnFor(row[col('Status')]));
      if (stamp >= 0 && isBlank(row[stamp])) writes.push({ row: r, col: stamp + 1, value: todayIso });
    }
    // A customer typed into a row with no job number makes it a new job
    if (edited('Customer') && col('Job ID') >= 0 &&
        !isBlank(row[col('Customer')]) && isBlank(row[col('Job ID')])) {
      const id = nextJobId(ids);
      ids.push(id);
      writes.push({ row: r, col: col('Job ID') + 1, value: id });
      if (col('Created') >= 0 && isBlank(row[col('Created')])) {
        writes.push({ row: r, col: col('Created') + 1, value: todayIso });
      }
    }
  });
  return writes;
}

/** Sheet rows to job objects keyed by column name. Rows with no job number or customer are skipped. */
function rowsToJobs(headers, rows) {
  return rows
    .map(function (row) {
      const job = {};
      headers.forEach(function (h, i) { if (h) job[h] = row[i]; });
      return job;
    })
    .filter(function (job) { return !isBlank(job['Job ID']) || !isBlank(job['Customer']); });
}

function dayNumber(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 86400000 : null;
}

/** Everything the Monday email needs, worked out from the jobs list. */
function buildSummary(jobs, todayIso, settings) {
  const today = dayNumber(todayIso);
  const chaseDays = Number(settings.chaseDays) || 7;
  const unpaidDays = Number(settings.unpaidDays) || 30;
  const withStatus = function (s) { return jobs.filter(function (j) { return j['Status'] === s; }); };
  const dated = function (field) { return function (j) { return dayNumber(j[field]) !== null; }; };
  const oldestFirst = function (field) {
    return function (a, b) { return dayNumber(a[field]) - dayNumber(b[field]); };
  };
  const withAge = function (field) {
    return function (j) { return Object.assign({}, j, { days: today - dayNumber(j[field]) }); };
  };

  const booked = withStatus('Booked').filter(dated('Scheduled')).sort(oldestFirst('Scheduled'));
  const nextWeek = booked.filter(function (j) {
    const ahead = dayNumber(j['Scheduled']) - today;
    return ahead >= 0 && ahead < 7;
  });
  const datePassed = booked.filter(function (j) { return dayNumber(j['Scheduled']) < today; });
  const chase = withStatus('Quoted').filter(dated('Quoted on')).sort(oldestFirst('Quoted on'))
    .map(withAge('Quoted on'))
    .filter(function (j) { return j.days >= chaseDays; });
  const unpaid = withStatus('Invoiced').filter(dated('Invoiced on')).sort(oldestFirst('Invoiced on'))
    .map(withAge('Invoiced on'))
    .map(function (j) { return Object.assign(j, { late: j.days > unpaidDays }); });
  const paid = withStatus('Paid').filter(function (j) {
    return String(j['Paid on'] || '').slice(0, 7) === todayIso.slice(0, 7);
  });

  return {
    today: todayIso,
    enquiries: withStatus('Enquiry').length,
    quotesOut: withStatus('Quoted').length,
    nextWeek: nextWeek,
    nextWeekValue: total(nextWeek),
    datePassed: datePassed,
    chase: chase,
    unpaid: unpaid,
    unpaidValue: total(unpaid),
    paidThisMonth: total(paid),
    paidThisMonthCount: paid.length,
  };
}

function total(jobs) {
  return jobs.reduce(function (sum, j) { return sum + (Number(j['Value £']) || 0); }, 0);
}

function money(n) {
  return '£' + Math.round(Number(n) || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** '2026-11-02' -> 'Mon 2 Nov' */
function shortDate(iso) {
  const n = dayNumber(iso);
  if (n === null) return '';
  const d = new Date(n * 86400000);
  return DAYS[d.getUTCDay()] + ' ' + d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()];
}

function escapeHtml(value) {
  return String(isBlank(value) ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function summarySubject(s, businessName) {
  return businessName + ': ' + s.nextWeek.length + ' jobs this week, ' +
    money(s.unpaidValue) + ' unpaid';
}

/** The Monday email as HTML. Every value from the sheet is escaped. */
function summaryHtml(s, businessName) {
  const cell = 'padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:left;';
  const table = function (title, jobs, columns, empty, isLate) {
    let html = '<h3 style="margin:22px 0 6px;font-size:15px">' + escapeHtml(title) + '</h3>';
    if (!jobs.length) return html + '<p style="margin:0;color:#64748b">' + escapeHtml(empty) + '</p>';
    html += '<table style="border-collapse:collapse;font-size:13px"><tr>';
    columns.forEach(function (c) {
      html += '<th style="' + cell + 'background:#f1f5f9;color:#475569">' + escapeHtml(c[0]) + '</th>';
    });
    html += '</tr>';
    jobs.forEach(function (j) {
      const style = isLate && isLate(j) ? cell + 'color:#b91c1c;font-weight:bold' : cell;
      html += '<tr>' + columns.map(function (c) {
        return '<td style="' + style + '">' + escapeHtml(c[1](j)) + '</td>';
      }).join('') + '</tr>';
    });
    return html + '</table>';
  };
  const field = function (name) { return function (j) { return j[name]; }; };
  const value = function (j) { return money(j['Value £']); };

  return '<div style="font-family:Arial,Helvetica,sans-serif;color:#1e293b;max-width:680px">' +
    '<h2 style="margin:0">' + escapeHtml(businessName) + '</h2>' +
    '<p style="margin:4px 0 0;color:#64748b">Week ahead from ' + escapeHtml(shortDate(s.today)) + '</p>' +
    '<p style="margin:16px 0 0;font-size:14px">' +
    s.nextWeek.length + ' jobs booked this week (' + money(s.nextWeekValue) + ') &middot; ' +
    s.chase.length + ' quotes to chase &middot; ' +
    s.unpaid.length + ' unpaid invoices (' + money(s.unpaidValue) + ') &middot; ' +
    money(s.paidThisMonth) + ' paid so far this month</p>' +
    table('Booked for the next 7 days', s.nextWeek, [
      ['Date', function (j) { return shortDate(j['Scheduled']); }], ['Customer', field('Customer')],
      ['Address', field('Address')], ['Job', field('Job type')], ['Engineer', field('Engineer')],
    ], 'Nothing booked yet.') +
    (s.datePassed.length ? table('Booked, but the date has passed: please update', s.datePassed, [
      ['Date', function (j) { return shortDate(j['Scheduled']); }], ['Job', field('Job ID')],
      ['Customer', field('Customer')], ['Engineer', field('Engineer')],
    ], '') : '') +
    table('Quotes to chase', s.chase, [
      ['Job', field('Job ID')], ['Customer', field('Customer')], ['Phone', field('Phone')],
      ['Value', value], ['Days waiting', field('days')],
    ], 'Nothing to chase.') +
    table('Unpaid invoices', s.unpaid, [
      ['Job', field('Job ID')], ['Customer', field('Customer')], ['Phone', field('Phone')],
      ['Value', value], ['Days unpaid', field('days')],
    ], 'All invoices are paid.', function (j) { return j.late; }) +
    '<p style="margin:24px 0 0;font-size:12px;color:#94a3b8">Sent by the job tracker. ' +
    'Turn it off from the Job tracker menu in the spreadsheet.</p></div>';
}

/**
 * Check and tidy what was typed into the "Add a job" form.
 * options: {statuses, jobTypes, engineers} from the Lists tab.
 * Returns {job, errors}: job is keyed by Jobs column names.
 */
function cleanJob(form, options) {
  const text = function (name) { return String(form[name] || '').trim(); };
  const errors = [];
  const job = {
    'Customer': text('Customer'),
    'Phone': text('Phone'),
    'Address': text('Address'),
    'Job type': text('Job type'),
    'Description': text('Description'),
    'Engineer': text('Engineer'),
    'Status': text('Status') || 'Enquiry',
    'Value £': '',
    'Scheduled': text('Scheduled'),
    'Notes': text('Notes'),
  };
  if (!job['Customer']) errors.push('Customer is required.');
  const oneOf = function (field, list) {
    if (job[field] && list && list.length && list.indexOf(job[field]) < 0) {
      errors.push(field + ' must be one of: ' + list.join(', ') + '.');
    }
  };
  oneOf('Status', options.statuses);
  oneOf('Job type', options.jobTypes);
  oneOf('Engineer', options.engineers);

  const rawValue = text('Value £').replace(/[£,\s]/g, '');
  if (rawValue) {
    const n = Number(rawValue);
    if (!isFinite(n) || n < 0) errors.push('Value must be a number of pounds, e.g. 250.');
    else job['Value £'] = n;
  }
  if (job['Scheduled'] && dayNumber(job['Scheduled']) === null) {
    errors.push('Scheduled must be a date.');
  }
  return { job: job, errors: errors };
}

/** Text starting with = + - @ would be read as a formula; a leading apostrophe stops that. */
function safeText(value) {
  return typeof value === 'string' && /^[=+\-@]/.test(value) ? "'" + value : value;
}

/** One new Jobs row, lined up with whatever column order the tab has. */
function jobToRow(headers, job, id, todayIso) {
  const stamp = stampColumnFor(job['Status']);
  return headers.map(function (h) {
    if (h === 'Job ID') return id;
    if (h === 'Created' || h === stamp) return todayIso;
    return safeText(isBlank(job[h]) ? '' : job[h]);
  });
}

// Lets Node load this file for the tests. Apps Script has no `module`, so it skips this.
if (typeof module !== 'undefined') {
  module.exports = {
    STAMP_COLUMNS, stampColumnFor, nextJobId, planEdits, rowsToJobs, dayNumber, buildSummary,
    money, shortDate, escapeHtml, summarySubject, summaryHtml, cleanJob, safeText, jobToRow,
  };
}

// Read only matching review replies; never mark mail read or alter unrelated mail.
function run(argv) {
  const mail = Application('Mail');
  const reviewer = argv[0];
  const messages = mail.inbox().messages.whose({sender: {_contains: reviewer}, subject: {_contains: 'Field station:'}})();
  const rows = [];
  for (const message of messages.sort((a,b) => b.dateReceived().getTime()-a.dateReceived().getTime()).slice(0,300)) {
    const subject = message.subject();
    const match = subject.match(/\[([a-f0-9]{12})\]/i);
    if (!match) continue;
    const sent = mail.sentMailbox().messages.whose({subject: {_contains: '[' + match[1] + ']'}})();
    rows.push({sender: message.sender(), subject: subject, content: message.content(), headers: message.allHeaders(), message_id: message.messageId(), received_epoch: message.dateReceived().getTime()/1000, sent_message_ids: sent.map(m => m.messageId())});
  }
  return JSON.stringify(rows);
}

// Read matching replies without changing Mail. Imported IDs avoid repeated body/header scans.
function run(argv) {
  const mail = Application('Mail'), reviewer = argv[0], known = new Set(JSON.parse(argv[1] || '[]'));
  const matching = mail.inbox().messages.whose({sender: {_contains: reviewer}, subject: {_contains: 'Field station:'}});
  const messages = matching(), ids = matching.messageId(), dates = matching.dateReceived();
  const pending = messages.map((message,i)=>({message,id:ids[i],epoch:dates[i].getTime()/1000}))
    .filter(row=>!known.has(row.id.replace(/^<|>$/g,'')))
    .sort((a,b)=>a.epoch-b.epoch).slice(0,5);
  if (!pending.length) return '[]';
  const sent = mail.sentMailbox().messages.whose({subject: {_contains: 'Field station:'}});
  const sentSubjects = sent.subject(), sentIds = sent.messageId(), byEvent = {};
  sentSubjects.forEach((subject,i)=>{const match=subject.match(/\[([a-f0-9]{12})\]/i);if(match)(byEvent[match[1]] ||= []).push(sentIds[i])});
  return JSON.stringify(pending.map(row=>{
    const message=row.message,subject=message.subject(),match=subject.match(/\[([a-f0-9]{12})\]/i);
    return {sender:message.sender(),subject,content:message.content(),headers:message.allHeaders(),message_id:row.id,received_epoch:row.epoch,sent_message_ids:match?(byEvent[match[1]]||[]):[]};
  }));
}

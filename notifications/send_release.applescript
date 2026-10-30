on run argv
    set senderAddress to item 1 of argv
    set recipientAddress to item 2 of argv
    set subjectText to item 3 of argv
    set bodyText to read (POSIX file (item 4 of argv)) as «class utf8»
    with timeout of 45 seconds
        tell application "Mail"
            set releaseMessage to make new outgoing message with properties {subject:subjectText, content:bodyText & return, visible:false, sender:senderAddress}
            tell releaseMessage
                make new to recipient at end of to recipients with properties {address:recipientAddress}
            end tell
            if sender of releaseMessage is not senderAddress then error "Mail changed the requested sender"
            if not (send releaseMessage) then error "Mail did not accept the outgoing message"
            return "accepted_by_mail"
        end tell
    end timeout
end run

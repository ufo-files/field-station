on run argv
    set senderAddress to item 1 of argv
    set recipientAddress to item 2 of argv
    set subjectText to item 3 of argv
    set bodyText to read (POSIX file (item 4 of argv)) as «class utf8»
    set screenshotFile to POSIX file (item 5 of argv) as alias
    with timeout of 45 seconds
        tell application "Mail"
            set senderFound to false
            repeat with mailAccount in every account
                if enabled of mailAccount and (email addresses of mailAccount contains senderAddress) then set senderFound to true
            end repeat
            if not senderFound then error "Requested sender is not configured in Apple Mail"
            set alertMessage to make new outgoing message with properties {subject:subjectText, content:bodyText & return, visible:false, sender:senderAddress}
            tell alertMessage
                make new to recipient at end of to recipients with properties {address:recipientAddress}
                make new attachment with properties {file name:screenshotFile} at after the last paragraph
            end tell
            if sender of alertMessage is not senderAddress then error "Mail changed the requested sender"
            if not (send alertMessage) then error "Mail did not accept the outgoing message"
            return "accepted_by_mail"
        end tell
    end timeout
end run

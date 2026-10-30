-- SPDX-License-Identifier: Apache-2.0
-- Shared owned-alert policy for Mac render and refresh. The Python owner
-- assembles this resource with an entry point before calling osascript.

-- Wording of the alerts Hancom raises when it refuses a document. Matching needs
-- one of these AND a lone 확인 button, so no other alert is ever dismissed.
property refusalPhrases : {"파일이 손상", "읽거나 저장하는데 오류", "읽거나 저장하는 데 오류", "PDF 파일을 저장하는데 오류", "PDF 파일을 저장하는 데 오류"}
property dismissButton : "확인"
-- The repair prompt for a broken table. Matching needs this wording AND exactly
-- the buttons 취소 and 복원; only 취소 is ever clicked on it.
property repairPhrase : "복원할까요"
property repairCancelButton : "취소"
property repairAcceptButton : "복원"
-- How long to keep dismissing the alerts Hancom raises after the repair prompt
-- is cancelled ("PDF 파일을 저장하는데 오류가 있습니다."). Bounded: the render ends
-- after it whatever Hancom does.
property followUpSecs : 5

on waitForDocumentOrRefusal(winName, beforeSigs, secs)
	repeat (secs * 2) times
		set refused to refusalResult(beforeSigs)
		if refused is not "" then return refused
		if listContains(windowNames(), winName) then return "OK"
		delay 0.5
	end repeat
	return "ERR: document window did not open: " & winName
end waitForDocumentOrRefusal

on alertSnapshot()
	set entries to {}
	try
		tell application "System Events" to tell process procName
			repeat with w in (every window)
				set e to my alertEntryOf(w)
				if e is not missing value then set end of entries to e
			end repeat
		end tell
	end try
	return entries
end alertSnapshot

on alertEntryOf(w)
	try
		tell application "System Events"
			set sr to ""
			try
				set sr to (subrole of w) as string
			end try
			set nm to ""
			try
				set nm to (name of w) as string
			end try
			if sr is not in {"AXDialog", "AXSystemDialog"} and nm is not "" then return missing value
			-- Read each text and button on its own: asking the window for all their
			-- values at once fails as a whole on a real Hancom alert, which left the
			-- alert's wording and its 확인 button unread (#143).
			set txt to nm
			try
				repeat with t in (static texts of w)
					try
						set txt to txt & linefeed & ((value of t) as string)
					end try
				end repeat
			end try
			set btns to {}
			try
				repeat with b in (buttons of w)
					try
						set bs to (name of b) as string
						if bs is not "" and bs is not "missing value" then set end of btns to bs
					end try
				end repeat
			end try
		end tell
		return {sig:sr & "|" & txt, txt:txt, btns:btns}
	on error
		return missing value
	end try
end alertEntryOf

on sigsOf(entries)
	set sigs to {}
	repeat with e in entries
		set end of sigs to (sig of e)
	end repeat
	return sigs
end sigsOf

on isRefusal(e)
	if (btns of e) is not {dismissButton} then return false
	repeat with phrase in refusalPhrases
		if (txt of e) contains (phrase as string) then return true
	end repeat
	return false
end isRefusal

-- Refusal alerts in `entries` whose signature was not up before the open.
on newRefusalAlerts(beforeSigs, entries)
	set found to {}
	repeat with e in entries
		if isRefusal(e) and not listContains(beforeSigs, sig of e) then set end of found to (contents of e)
	end repeat
	return found
end newRefusalAlerts

-- A repair prompt: the wording, and exactly the buttons 취소 and 복원 in any order.
on isRepairPrompt(e)
	set bs to btns of e
	if (count of bs) is not 2 then return false
	if bs does not contain repairCancelButton or bs does not contain repairAcceptButton then return false
	return (txt of e) contains repairPhrase
end isRepairPrompt

-- Repair prompts in `entries` whose signature was not up before the open.
on newRepairPrompts(beforeSigs, entries)
	set found to {}
	repeat with e in entries
		if isRepairPrompt(e) and not listContains(beforeSigs, sig of e) then set end of found to (contents of e)
	end repeat
	return found
end newRepairPrompts

-- "" while no alert of ours is up; otherwise dismiss it (only when exactly one
-- can be ours) and return the HANCOM_REFUSED line. A repair prompt of ours is
-- cancelled, and the alerts Hancom raises after that are dismissed as well.
on refusalResult(beforeSigs)
	set entries to alertSnapshot()
	set prompts to newRepairPrompts(beforeSigs, entries)
	if (count of prompts) > 0 then
		set answer to "ERR: HANCOM_REFUSED: " & refusalLine(txt of item 1 of prompts)
		if (count of prompts) > 1 then return answer & " (prompt left up: more than one matched)"
		if not cancelRepairPrompt(sig of item 1 of prompts) then return answer & " (prompt left up: cancel failed)"
		dismissFollowUpAlerts(beforeSigs, followUpSecs)
		return answer
	end if
	set found to newRefusalAlerts(beforeSigs, entries)
	if (count of found) is 0 then return ""
	set answer to "ERR: HANCOM_REFUSED: " & refusalLine(txt of item 1 of found)
	if (count of found) > 1 then return answer & " (alert left up: more than one matched)"
	if not dismissAlert(sig of item 1 of found) then return answer & " (alert left up: dismiss failed)"
	return answer
end refusalResult

on dismissAlert(theSig)
	-- Re-find the window right before clicking; click only a unique match.
	try
		tell application "System Events" to tell process procName
			set target to missing value
			repeat with w in (every window)
				set e to my alertEntryOf(w)
				if e is not missing value then
					if (sig of e) is theSig then
						if target is not missing value then return false
						set target to contents of w
					end if
				end if
			end repeat
			if target is missing value then return false
			click button dismissButton of target
		end tell
	on error
		return false
	end try
	repeat 10 times
		if not listContains(sigsOf(alertSnapshot()), theSig) then return true
		delay 0.3
	end repeat
	return false
end dismissAlert

-- The same re-find-then-click-a-unique-match as dismissAlert, for the repair
-- prompt: the only button ever clicked on it is 취소 (repairCancelButton).
on cancelRepairPrompt(theSig)
	try
		tell application "System Events" to tell process procName
			set target to missing value
			repeat with w in (every window)
				set e to my alertEntryOf(w)
				if e is not missing value then
					if (sig of e) is theSig then
						if target is not missing value then return false
						set target to contents of w
					end if
				end if
			end repeat
			if target is missing value then return false
			click button repairCancelButton of target
		end tell
	on error
		return false
	end try
	repeat 10 times
		if not listContains(sigsOf(alertSnapshot()), theSig) then return true
		delay 0.3
	end repeat
	return false
end cancelRepairPrompt

-- After 취소 on the repair prompt Hancom gives up the export and raises one more
-- alert ("PDF 파일을 저장하는데 오류가 있습니다.", lone 확인). Keep dismissing new
-- refusal alerts for a bounded while so none of this render's is left up; as
-- everywhere, only an alert that was not up before the open, and only a unique one.
on dismissFollowUpAlerts(beforeSigs, secs)
	repeat (secs * 2) times
		set found to newRefusalAlerts(beforeSigs, alertSnapshot())
		if (count of found) is 1 then dismissAlert(sig of item 1 of found)
		delay 0.5
	end repeat
end dismissFollowUpAlerts

on refusalLine(txt)
	set parts to {}
	repeat with p in paragraphs of txt
		set t to trimmed(p as string)
		if t is not "" then set end of parts to t
	end repeat
	set saved to AppleScript's text item delimiters
	set AppleScript's text item delimiters to " / "
	set joined to parts as string
	set AppleScript's text item delimiters to saved
	return joined
end refusalLine

on trimmed(t)
	set blanks to {" ", tab, return, linefeed}
	repeat while t is not "" and (character 1 of t) is in blanks
		if (length of t) is 1 then return ""
		set t to text 2 thru -1 of t
	end repeat
	repeat while t is not "" and (character -1 of t) is in blanks
		if (length of t) is 1 then return ""
		set t to text 1 thru -2 of t
	end repeat
	return t
end trimmed

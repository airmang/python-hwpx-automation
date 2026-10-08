-- SPDX-License-Identifier: Apache-2.0
-- Mac Hancom (한컴오피스 한글) render backend for the VisualComplete oracle.
--
-- This build of Hancom Office HWP (com.hancom.office.hwp12.mac.general) ships
-- NO AppleScript dictionary (sdef) and NO headless convert CLI, so PDF export is
-- GUI-only. This script drives that GUI deterministically through System Events
-- (UI scripting), the Mac analogue of the Windows COM backend (_render_hwpx.ps1).
--
-- Flow, anchored on STABLE MENU-ITEM NAMES (prefix match), not pixels:
--   open <input>  ->  파일 (File) > "PDF로 저장하기..."  ->  NSSavePanel
--   -> Return (= the default 저장 button)  ->  파일 > "문서 닫기"
--
-- Why no typing is needed: the save panel is document-relative — it pre-fills
--   위치 (location) = the input file's directory and the name field = the input
--   stem. The Python caller therefore STAGES the input as <out_dir>/<out_stem>.hwpx,
--   so pressing 저장 writes exactly <out_dir>/<out_stem>.pdf. The caller also
--   pre-deletes the target, so the "대치(replace)?" sheet never appears in normal
--   operation; it is still dismissed defensively here. A "문서 닫기" save-changes
--   prompt is likewise discarded (we only exported; the doc is unmodified).
--
-- A document Hancom refuses to open raises a one-button alert (e.g. "파일이
-- 손상되었습니다"). Left up, it blocks every later render on this Mac, from
-- any process. So the alert-like windows are snapshotted just before the open;
-- a refusal alert that appears after it is this render's, is dismissed with its
-- lone 확인 button, and ends the render at once as HANCOM_REFUSED. An alert that
-- was already up belongs to someone else and is never touched.
--
-- A document with a broken table (e.g. a bad cellSpan) makes Hancom ask during
-- the export whether to repair it ("손상된 표를 복원할까요?", buttons 취소 and
-- 복원). A new such prompt is this render's: it is answered 취소 — never 복원,
-- which would render a document Hancom rewrote instead of the one given — and
-- the render ends as HANCOM_REFUSED. Hancom then reports that the PDF could not
-- be saved; that alert is dismissed too, so nothing is left up.
--
-- Usage:  osascript _render_hwpx_mac.applescript <input.hwpx> <out.pdf> [timeoutSecs]
-- Output: prints "OK" on success; prints "ERR: <reason>" otherwise, and
--         "ERR: HANCOM_REFUSED: <alert text>" when Hancom refused the document.

property procName : "Hancom Office HWP"
property appName : "Hancom Office HWP"
property pdfDialogTitle : "PDF로 저장하기"
property fileMenuName : "파일"
property savePdfPrefix : "PDF로 저장하기"
property closeDocPrefix : "문서 닫기"
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

on run argv
	if (count of argv) < 2 then return "ERR: usage: <input.hwpx> <out.pdf> [timeoutSecs]"
	if item 1 of argv is "--close-owned" then
		closeOwnedDocument(item 2 of argv)
		return "CLEANUP"
	end if
	set inputPath to item 1 of argv
	set outPdf to item 2 of argv
	set timeoutSecs to 90
	if (count of argv) ≥ 3 then
		try
			set timeoutSecs to (item 3 of argv) as integer
		end try
	end if

	set inputBase to do shell script "basename " & quoted form of inputPath

	if listContains(windowNames(), inputBase) then return "ERR: staged document already open"
	if listContains(windowNames(), pdfDialogTitle) then return "ERR: existing PDF dialog"
	-- Do not drive menus while another document owns a modal sheet.
	tell application "System Events"
		if exists process procName then
			tell process procName
				repeat with w in windows
					if (count of sheets of w) > 0 then return "ERR: existing modal sheet"
				end repeat
			end tell
		end if
	end tell
	-- Every alert already up is someone else's; only a new one can be ours.
	set beforeSigs to sigsOf(alertSnapshot())
	try
		-- 1) Open the staged input. LaunchServices focuses Hancom (launching it
		--    if needed) and opens the document.
		do shell script "open -a " & quoted form of appName & " " & quoted form of inputPath

		-- 2) Wait for the document window to exist, or for Hancom to refuse it.
		set opened to waitForDocumentOrRefusal(inputBase, beforeSigs, timeoutSecs)
		if opened is not "OK" then
			if opened starts with "ERR: HANCOM_REFUSED" then closeOwnedDocument(inputBase)
			return opened
		end if
		-- A prior timed-out render can leave a same-named window behind, and
		-- LaunchServices does not guarantee that the newly opened document is
		-- frontmost. Raise the exact staged document before using its File menu.
		raiseWindowNamed(inputBase)
		delay 0.3

		-- 3) 파일 > "PDF로 저장하기..."  (open the export save panel)
		clickFileMenuItemByPrefix(savePdfPrefix)

		-- 4) Wait for the export dialog.
		if not (waitForWindowNamed(pdfDialogTitle, 30)) then
			error "PDF save dialog did not appear"
		end if
		delay 1.0

		-- 5) Press Return = the default 저장 button (no typing: panel is
		--    pre-filled with 위치=out_dir, name=out_stem from the staged input).
		tell application "System Events" to tell process procName
			set frontmost to true
			delay 0.3
			key code 36 -- Return
		end tell
		-- Some Hancom builds expose the dialog before its default button is
		-- ready. Retry Return once only while the same dialog is still present.
		delay 1.0
		-- Never while a repair prompt of ours is up: Return would press its
		-- default button, which may be 복원.
		if listContains(windowNames(), pdfDialogTitle) and (count of newRepairPrompts(beforeSigs, alertSnapshot())) is 0 then
			tell application "System Events" to tell process procName
				set frontmost to true
				key code 36
			end tell
		end if

		-- 6) Defensive: a "대치(replace)?" sheet only appears if the target still
		--    exists. Dismiss it (대치) if present, then wait for the file.
		dismissOverwriteSheetIfPresent()

		-- 7) The render is asynchronous — wait until the PDF lands at out_pdf and
		--    the dialog has closed. Hancom can still refuse while exporting.
		set written to waitForFileOrRefusal(outPdf, beforeSigs, timeoutSecs)
		if written starts with "ERR: HANCOM_REFUSED" then
			waitForWindowGone(pdfDialogTitle, 5)
			closeOwnedDocument(inputBase)
			return written
		end if
		set wrote to (written is "OK")
		waitForWindowGone(pdfDialogTitle, 15)

		-- 8) Always close the document so the next render starts from a clean
		--    session, even if the wait above was noisy. Discard any save-changes
		--    prompt (we only exported; the doc content is unmodified).
		set closed to closeOwnedDocument(inputBase)
		if not closed then return "ERR: owned document cleanup incomplete"

		if not wrote then return "ERR: PDF not written to " & outPdf
		return "OK"
	on error errMsg number errNum
		-- Best-effort cleanup so a mid-flow error doesn't leak an open document.
		closeOwnedDocument(inputBase)
		return "ERR: " & errMsg & " (" & errNum & ")"
	end try
end run

-- Find the 파일 menu by name, then click the first menu item whose name starts
-- with `prefix`. Name-based so it survives index drift across Hancom versions.
on clickFileMenuItemByPrefix(prefix)
	tell application "System Events" to tell process procName
		set frontmost to true
		delay 0.2
		set fileMenu to missing value
		repeat with mbi in menu bar items of menu bar 1
			if (name of mbi as string) is fileMenuName then
				set fileMenu to menu 1 of mbi
				exit repeat
			end if
		end repeat
		if fileMenu is missing value then error "menu '" & fileMenuName & "' not found"
		repeat with mi in menu items of fileMenu
			try
				if (name of mi as string) starts with prefix then
					click mi
					return
				end if
			end try
		end repeat
		error "menu item not found: " & prefix
	end tell
end clickFileMenuItemByPrefix

on raiseWindowNamed(winName)
	tell application "System Events" to tell process procName
		set frontmost to true
		try
			perform action "AXRaise" of (first window whose name is winName)
		end try
	end tell
end raiseWindowNamed

-- Window polling uses the ATOMIC ``name of windows`` string list (never a held
-- ``repeat with w in windows`` element reference): the save dialog appears and
-- disappears mid-flow, so a lazily-resolved ``item N of every window`` can become
-- an invalid index (-1719). Snapshotting names and guarding with ``try`` is
-- race-safe.
on windowNames()
	try
		tell application "System Events" to tell process procName
			return (name of windows) as list
		end tell
	on error
		return {}
	end try
end windowNames

on listContains(theList, theValue)
	repeat with x in theList
		-- a window without a title (missing value) cannot become a string
		try
			if (x as string) is theValue then return true
		end try
	end repeat
	return false
end listContains

on waitForWindowNamed(winName, secs)
	repeat (secs * 2) times
		if listContains(windowNames(), winName) then return true
		delay 0.5
	end repeat
	return false
end waitForWindowNamed

on waitForWindowGone(winName, secs)
	repeat (secs * 2) times
		if not (listContains(windowNames(), winName)) then return true
		delay 0.5
	end repeat
	return false
end waitForWindowGone

on waitForDocumentOrRefusal(winName, beforeSigs, secs)
	repeat (secs * 2) times
		set refused to refusalResult(beforeSigs)
		if refused is not "" then return refused
		if listContains(windowNames(), winName) then return "OK"
		delay 0.5
	end repeat
	return "ERR: document window did not open: " & winName
end waitForDocumentOrRefusal

on waitForFileOrRefusal(p, beforeSigs, secs)
	-- size>0 alone is NOT completion: Hancom streams the PDF asynchronously and
	-- closing the document mid-write truncates it (measured: a TOC-regenerating
	-- document produced a deterministic %%EOF-less torso). Require the PDF
	-- trailer marker so the export has actually finished before we move on.
	repeat (secs * 2) times
		if (do shell script "test -s " & quoted form of p & " && tail -c 64 " & quoted form of p & " | grep -q '%%EOF' && echo 1 || echo 0") is "1" then
			return "OK"
		end if
		set refused to refusalResult(beforeSigs)
		if refused is not "" then return refused
		delay 0.5
	end repeat
	return "TIMEOUT"
end waitForFileOrRefusal

-- ---------------------------------------------------------------------------
-- Refusal alerts. A snapshot entry is {sig, txt, btns} for each Hancom window
-- that could be an alert (a dialog subrole, or no title). sig is what "the same
-- window before and after the open" is judged by; windows carry no stable id.
-- ---------------------------------------------------------------------------
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

-- The overwrite confirmation is a SHEET of the PDF dialog window; its buttons are
-- directly accessible (unlike the save panel's own nested buttons). Re-fetch the
-- window by name each pass and guard, since it is being torn down concurrently.
on dismissOverwriteSheetIfPresent()
	repeat 6 times
		try
			tell application "System Events" to tell process procName
				set dlg to (first window whose name is pdfDialogTitle)
				if (count of sheets of dlg) > 0 then
					tell sheet 1 of dlg
						if (exists button "대치") then
							click button "대치"
							return true
						end if
					end tell
				end if
			end tell
		end try
		delay 0.3
	end repeat
	return false
end dismissOverwriteSheetIfPresent

-- Never discard a sheet belonging to any other document. If ownership cannot
-- be proved, leave the GUI for the user and report failure rather than kill it.
on closeOwnedDocument(winName)
    if not listContains(windowNames(), winName) then return false
    if listContains(windowNames(), pdfDialogTitle) then return false
    try
        raiseWindowNamed(winName)
        tell application "System Events" to tell process procName
            if name of front window is not winName then return false
        end tell
        clickFileMenuItemByPrefix(closeDocPrefix)
        tell application "System Events" to tell process procName
            if exists (first window whose name is winName) then
                set owned to (first window whose name is winName)
                if (count of sheets of owned) > 0 then
                    repeat with b in buttons of sheet 1 of owned
                        try
                            set bn to name of b as string
                            if bn contains "안 함" or bn contains "안함" then click b
                        end try
                    end repeat
                end if
            end if
        end tell
        return waitForWindowGone(winName, 2)
    on error
        return false
    end try
end closeOwnedDocument

import QtQuick
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "andean-bridge.notification-rules-mgr"
  ipcTarget: "andean-bridge.notification-rules-mgr"
  manageIpc: false
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property color ink: Color.popups.text
  readonly property color softInk: Qt.rgba(ink.r, ink.g, ink.b, 0.58)
  readonly property color hairline: Qt.rgba(ink.r, ink.g, ink.b, 0.13)
  readonly property color tint: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.12)
  readonly property string face: bar ? bar.fontFamily : Style.font.family
  readonly property string backend: Quickshell.env("OMARCHY_NOTIFICATION_RULES_BACKEND") ||
    (Quickshell.env("HOME") + "/.config/omarchy/plugins/andean-bridge.notification-rules-mgr/backend.py")

  property var payload: null
  readonly property var config: payload && payload.config ? payload.config : ({})
  readonly property var rules: config.rules || []
  readonly property var crashes: payload && payload.crashes ? payload.crashes : []
  readonly property var notifications: payload && payload.notifications ? payload.notifications : []
  readonly property var muteDurations: [
    { key: "hour", label: "1h" },
    { key: "eight_hours", label: "8h" },
    { key: "seven_days", label: "7d" },
    { key: "forever", label: "Forever" }
  ]
  property string tab: "Home"
  property string searchText: ""
  property string duration: "hour"
  property string quickDuration: "hour"
  property string scope: "All"
  property bool busy: false
  property string pendingAction: ""
  property string notice: ""
  property bool noticeError: false
  property bool recentMode: false

  function open() { controller.show(); request("read", []) }
  function close() { controller.hide() }
  function toggle() { opened ? close() : open() }
  function request(action, args) {
    if (busy) return
    busy = true
    pendingAction = action
    backendProcess.command = ["python3", backend, action].concat(args || [])
    backendProcess.running = true
  }
  function fmtTime(seconds) {
    if (!seconds) return ""
    return Qt.formatDateTime(new Date(seconds * 1000), "MMM d · h:mm AP")
  }
  function expiry(rule) {
    if (rule.untilSessionEnd) return "until Debugging ends"
    if (rule.expiresAt) return "until " + fmtTime(rule.expiresAt)
    return "always"
  }
  function filteredCrashes() {
    var needle = searchText.toLowerCase().trim()
    return crashes.filter(function(row) { return !needle || row.name.toLowerCase().includes(needle) })
  }
  function filteredNotifications() {
    var needle = searchText.toLowerCase().trim()
    return notifications.filter(function(row) {
      return !needle || (row.app + " " + row.summary + " " + row.body).toLowerCase().includes(needle)
    })
  }
  function filteredRules() {
    var needle = searchText.toLowerCase().trim()
    return rules.filter(function(row) { return !needle || row.process.toLowerCase().includes(needle) })
  }
  function addRule(processName) {
    var name = String(processName || "").trim()
    if (!name) { notice = "Enter a process name"; noticeError = true; return }
    request("add", [name, "silence", duration, scope])
  }
  function quickMute(processName) {
    var name = String(processName || "").trim()
    if (!name) { notice = "Enter a process name"; noticeError = true; return }
    request("add", [name, "silence", quickDuration, "All"])
  }

  Process {
    id: backendProcess
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var next = JSON.parse(String(text || ""))
          if (!next.ok) throw new Error(next.error || "Unknown error")
          root.payload = next
          root.notice = next.status || ""
          root.noticeError = false
          if (root.pendingAction === "add") processInput.text = ""
        } catch (error) {
          root.notice = "Could not update: " + error
          root.noticeError = true
        }
        root.busy = false
        root.pendingAction = ""
      }
    }
  }
  Timer {
    interval: 60000
    repeat: true
    running: true
    onTriggered: if (!root.busy) root.request("tick", [])
  }
  Component.onCompleted: request("tick", [])

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.payload && (root.payload.quietActive || root.payload.effectiveDnd) ? "󰂛" : "󰂚"
    active: root.payload && (root.payload.quietActive || root.payload.effectiveDnd)
    onPressed: root.toggle()
  }

  KeyboardPanel {
    id: popup
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: popup.fittedContentWidth(Style.space(500))
    contentHeight: popup.fittedContentHeight(mainColumn.implicitHeight, Style.space(690))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: processInput.activeFocus || searchInput.activeFocus || startInput.activeFocus || endInput.activeFocus || dedupeInput.activeFocus
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) {
        if (dy !== 0) scroller.contentY = Math.max(0, Math.min(scroller.contentHeight - scroller.height, scroller.contentY + dy * 56))
      }

      Flickable {
        id: scroller
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: mainColumn.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        QQC.ScrollBar.vertical: QQC.ScrollBar { policy: QQC.ScrollBar.AsNeeded }

        Column {
          id: mainColumn
          width: scroller.width
          spacing: Style.space(14)

          Rectangle {
            id: hero
            width: parent.width
            height: 128
            radius: Style.cornerRadius * 1.5
            color: root.tint
            border.width: 1
            border.color: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.32)
            clip: true

            Rectangle {
              width: 190; height: 190; radius: 95
              x: parent.width - 125; y: -95
              color: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.08)
              border.width: 1
              border.color: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.12)
            }
            Column {
              anchors.left: parent.left; anchors.leftMargin: 22
              anchors.verticalCenter: parent.verticalCenter
              spacing: 7
              Text {
                text: "NOTIFICATION RULES"
                textFormat: Text.PlainText
                color: Color.accent
                font.family: root.face; font.pixelSize: Style.font.caption
                font.bold: true; font.letterSpacing: 2
              }
              Text {
                text: "Your attention, by design."
                textFormat: Text.PlainText
                color: root.ink
                font.family: root.face; font.pixelSize: Style.font.heading + 3
                font.bold: true
              }
              Text {
                text: (root.config.activeProfile || "Normal") + " mode  ·  " +
                  (root.payload && root.payload.quietActive ? "Quiet hours on" :
                    root.payload && root.payload.effectiveDnd ? "Do Not Disturb on" : "Notifications on")
                textFormat: Text.PlainText
                color: root.softInk
                font.family: root.face; font.pixelSize: Style.font.body
              }
            }
          }

          Row {
            width: parent.width
            spacing: 7
            Repeater {
              model: ["Normal", "Focus", "Presenting", "Debugging"]
              Pill {
                required property string modelData
                label: modelData
                selected: root.config.activeProfile === modelData
                enabled: !root.busy
                onClicked: { root.scope = "All"; root.request("profile", [modelData]) }
              }
            }
          }

          Row {
            width: parent.width
            spacing: 7
            Repeater {
              model: ["Home", "Rules", "Activity", "Settings"]
              Pill {
                required property string modelData
                label: modelData
                selected: root.tab === modelData
                subtle: true
                onClicked: { root.tab = modelData; scroller.contentY = 0; root.searchText = ""; searchInput.text = "" }
              }
            }
          }

          Rectangle {
            width: parent.width; height: 1; color: root.hairline
          }

          // Home: a focused summary and the fastest path to an exact crash mute.
          Column {
            visible: root.tab === "Home"
            width: parent.width
            spacing: Style.space(14)

            Row {
              width: parent.width; spacing: 9
              StatCard { label: "ACTIVE RULES"; value: String(root.rules.length); detail: "exact processes"; width: (parent.width - 18) / 3 }
              StatCard { label: "CRASHES"; value: String(root.crashes.length); detail: "processes logged"; width: (parent.width - 18) / 3 }
              StatCard { label: "DISTRACTIONS"; value: root.payload && root.payload.effectiveDnd ? "Quiet" : "Open"; detail: "global DND"; width: (parent.width - 18) / 3 }
            }

            Card {
              width: parent.width
              SectionHeading { text: "Mute a crash alert"; trailing: "EXACT PROCESS" }
              Text { width: parent.width; wrapMode: Text.WordWrap; text: "Other crash alerts keep working. Muted crashes remain in the system journal."; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.bodySmall }
              Row {
                width: parent.width; spacing: 6
                Repeater {
                  model: root.muteDurations
                  Pill { required property var modelData; label: modelData.label; selected: root.quickDuration === modelData.key; onClicked: root.quickDuration = modelData.key }
                }
              }
              Row {
                width: parent.width; spacing: 8
                Input { id: processInput; width: parent.width - muteButton.width - 8; placeholderText: "e.g. MSBuild"; onAccepted: root.quickMute(text) }
                Pill { id: muteButton; label: "Mute now"; selected: true; enabled: !root.busy; onClicked: root.quickMute(processInput.text) }
              }
            }

            Card {
              width: parent.width
              SectionHeading { text: "At a glance"; trailing: "LIVE CONTROLS" }
              Row {
                width: parent.width; spacing: 8
                Pill { label: root.payload && root.payload.effectiveDnd ? "󰂛  DND on" : "󰂚  DND off"; selected: root.payload && root.payload.effectiveDnd; enabled: !root.busy; onClicked: root.request("dnd", [root.payload && root.payload.effectiveDnd ? "off" : "on"]) }
                Pill { label: root.payload && root.payload.captureEnabled ? "󰩡  Crash alerts on" : "󰩡  Crash alerts off"; selected: root.payload && root.payload.captureEnabled; enabled: !root.busy; onClicked: root.request("capture", [root.payload && root.payload.captureEnabled ? "off" : "on"]) }
              }
              Text { width: parent.width; wrapMode: Text.WordWrap; text: "Focus uses DND. Presenting also pauses all crash alerts. Critical and Omarchy action notifications may bypass DND."; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.bodySmall }
            }

            Card {
              width: parent.width
              SectionHeading { text: "Recent crashes"; trailing: "FROM SYSTEM JOURNAL" }
              Text { visible: root.crashes.length === 0; text: "Nothing recorded recently"; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.body }
              Repeater {
                model: root.crashes.slice(0, 3)
                CrashRow { required property var modelData; entry: modelData; width: parent.width }
              }
              Pill { visible: root.crashes.length > 0; label: "See all activity  →"; subtle: true; onClicked: root.tab = "Activity" }
            }
          }

          // Rules: explicit matching and expiry are visible for every rule.
          Column {
            visible: root.tab === "Rules"
            width: parent.width; spacing: Style.space(14)
            SectionHeading { text: "Crash rules"; trailing: String(root.rules.length) + " SAVED"; width: parent.width }
            Text { width: parent.width; wrapMode: Text.WordWrap; text: "A rule matches the executable name exactly. Alerts for other processes still appear."; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.body }
            Card {
              width: parent.width
              SectionHeading { text: "New rule"; trailing: "MUTE" }
              Input { width: parent.width; placeholderText: "Process name, such as MSBuild"; text: processInput.text; onTextEdited: processInput.text = text; onAccepted: root.addRule(text) }
              Text { text: "DURATION"; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1.2 }
              Row {
                width: parent.width; spacing: 6
                Repeater {
                  model: [ { key: "hour", label: "1 hour" }, { key: "eight_hours", label: "8 hours" }, { key: "seven_days", label: "7 days" }, { key: "forever", label: "Forever" } ]
                  Pill { required property var modelData; label: modelData.label; selected: root.duration === modelData.key; enabled: modelData.key !== "session" || root.config.activeProfile === "Debugging"; onClicked: root.duration = modelData.key }
                }
              }
              Row {
                width: parent.width; spacing: 6
                Pill { label: "Until tomorrow"; selected: root.duration === "tomorrow"; onClicked: root.duration = "tomorrow" }
                Pill { label: "Debug session"; selected: root.duration === "session"; enabled: root.config.activeProfile === "Debugging"; onClicked: root.duration = "session" }
              }
              Text { text: "APPLIES TO"; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1.2 }
              Row {
                width: parent.width; spacing: 6
                Pill { label: "All profiles"; selected: root.scope === "All"; onClicked: root.scope = "All" }
                Pill { label: "Current profile"; selected: root.scope !== "All"; onClicked: root.scope = root.config.activeProfile || "Normal" }
              }
              Pill { label: "Add mute rule  →"; selected: true; enabled: !root.busy; onClicked: root.addRule(processInput.text) }
            }
            Input { id: searchInput; width: parent.width; visible: root.rules.length > 5 || root.tab === "Activity"; placeholderText: "Search rules"; onTextEdited: root.searchText = text }
            Text { visible: root.rules.length === 0; text: "No rules yet. Add one above or mute directly from Activity."; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.body }
            Repeater {
              model: root.filteredRules()
              Card {
                required property var modelData
                width: parent.width
                Row {
                  width: parent.width; spacing: 8
                  Column {
                    width: parent.width - removeRule.width - 8; spacing: 4
                    Text { text: modelData.process; color: root.ink; font.family: root.face; font.pixelSize: Style.font.title; font.bold: true; elide: Text.ElideRight; width: parent.width }
                    Text { text: "Muted · " + modelData.profile + " · " + root.expiry(modelData); color: root.softInk; font.family: root.face; font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight; width: parent.width }
                  }
                  Pill { id: removeRule; label: "Remove"; subtle: true; enabled: !root.busy; onClicked: root.request("remove", [modelData.id]) }
                }
              }
            }
          }

          // Activity: journal-backed crash grouping plus Omarchy's recent list.
          Column {
            visible: root.tab === "Activity"
            width: parent.width; spacing: Style.space(14)
            SectionHeading { text: "Activity"; trailing: "SEARCHABLE"; width: parent.width }
            Row {
              width: parent.width; spacing: 6
              Pill { label: "Crash inbox"; selected: !root.recentMode; onClicked: { root.recentMode = false; root.searchText = ""; searchInput.text = "" } }
              Pill { label: "Recent notifications"; selected: root.recentMode; onClicked: { root.recentMode = true; root.searchText = ""; searchInput.text = "" } }
            }
            Input { width: parent.width; placeholderText: root.recentMode ? "Search recent notifications" : "Search crashed processes"; onTextEdited: root.searchText = text }
            Text { width: parent.width; wrapMode: Text.WordWrap; text: root.recentMode ? "Crash alerts below can be muted by process. Other notifications are shown from Omarchy's short recent list." : "Grouped by executable from systemd's crash journal. Muted crashes remain here."; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.bodySmall }
            Text { visible: !root.recentMode && root.filteredCrashes().length === 0; text: "No matching crashes"; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.body }
            Repeater {
              model: root.recentMode ? [] : root.filteredCrashes()
              CrashRow { required property var modelData; entry: modelData; width: parent.width }
            }
            Text { visible: root.recentMode && root.filteredNotifications().length === 0; text: "No matching recent notifications"; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.body }
            Repeater {
              model: root.recentMode ? root.filteredNotifications() : []
              Card {
                id: recentCard
                required property var modelData
                width: parent.width
                Text { text: modelData.app.toUpperCase() + "  ·  " + root.fmtTime(modelData.timestamp); color: root.softInk; font.family: root.face; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 0.8; width: parent.width; elide: Text.ElideRight }
                Text { text: modelData.summary; color: root.ink; font.family: root.face; font.pixelSize: Style.font.title; font.bold: true; width: parent.width; elide: Text.ElideRight }
                Text { visible: modelData.body !== ""; text: modelData.body; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.bodySmall; width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
                Column {
                  visible: !!modelData.crashProcess
                  width: parent.width; spacing: 7
                  Text { text: modelData.policy === "allowed" ? "MUTE THIS PROCESS FOR" : "CHANGE THIS PROCESS MUTE"; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1 }
                  Row {
                    spacing: 6
                    Repeater {
                      model: root.muteDurations
                      Pill { required property var modelData; label: modelData.label; enabled: !root.busy; onClicked: root.request("add", [recentCard.modelData.crashProcess, "silence", modelData.key, "All"]) }
                    }
                  }
                }
              }
            }
            Row {
              visible: root.recentMode; spacing: 7
              Pill { label: "Show recent"; selected: true; enabled: !root.busy; onClicked: root.request("replay", []) }
              Pill { label: "Dismiss visible"; subtle: true; enabled: !root.busy; onClicked: root.request("dismiss", []) }
              Pill { label: "Clear recent history"; subtle: true; enabled: !root.busy; onClicked: root.request("clear", []) }
            }
          }

          Column {
            visible: root.tab === "Settings"
            width: parent.width; spacing: Style.space(14)
            SectionHeading { text: "Settings"; trailing: "AUTOMATION"; width: parent.width }
            Card {
              width: parent.width
              SectionHeading { text: "Quiet hours"; trailing: root.payload && root.payload.quietActive ? "ACTIVE NOW" : "SCHEDULE" }
              Text { width: parent.width; wrapMode: Text.WordWrap; text: "During these hours, turn on DND and pause crash alerts. A crash summary can arrive when quiet hours end."; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.bodySmall }
              Row {
                spacing: 7
                Pill { label: root.config.quietHours && root.config.quietHours.enabled ? "Enabled" : "Disabled"; selected: !!(root.config.quietHours && root.config.quietHours.enabled); enabled: !root.busy; onClicked: root.request("quiet", [root.config.quietHours && root.config.quietHours.enabled ? "off" : "on", startInput.text, endInput.text, root.config.quietHours && root.config.quietHours.digest ? "on" : "off"]) }
                Pill { label: root.config.quietHours && root.config.quietHours.digest ? "Digest on" : "Digest off"; selected: !!(root.config.quietHours && root.config.quietHours.digest); enabled: !root.busy; onClicked: root.request("quiet", [root.config.quietHours && root.config.quietHours.enabled ? "on" : "off", startInput.text, endInput.text, root.config.quietHours && root.config.quietHours.digest ? "off" : "on"]) }
              }
              Row {
                width: parent.width; spacing: 8
                Input { id: startInput; width: (parent.width - 8) / 2; placeholderText: "Start HH:MM"; text: root.config.quietHours ? root.config.quietHours.start : "22:00" }
                Input { id: endInput; width: (parent.width - 8) / 2; placeholderText: "End HH:MM"; text: root.config.quietHours ? root.config.quietHours.end : "08:00" }
              }
              Pill { label: "Save hours  →"; selected: true; enabled: !root.busy; onClicked: root.request("quiet", [root.config.quietHours && root.config.quietHours.enabled ? "on" : "off", startInput.text, endInput.text, root.config.quietHours && root.config.quietHours.digest ? "on" : "off"]) }
            }
            Card {
              width: parent.width
              SectionHeading { text: "Crash alerts"; trailing: "SOURCE CONTROL" }
              Row {
                spacing: 7
                Pill { label: root.payload && root.payload.captureEnabled ? "Capture on" : "Capture off"; selected: root.payload && root.payload.captureEnabled; enabled: !root.busy; onClicked: root.request("capture", [root.payload && root.payload.captureEnabled ? "off" : "on"]) }
                Pill { label: root.payload && root.payload.effectiveDnd ? "DND on" : "DND off"; selected: root.payload && root.payload.effectiveDnd; enabled: !root.busy; onClicked: root.request("dnd", [root.payload && root.payload.effectiveDnd ? "off" : "on"]) }
              }
              Text { width: parent.width; wrapMode: Text.WordWrap; text: "Repeat window for the same crashed process (10–3600 seconds)"; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.bodySmall }
              Row {
                width: parent.width; spacing: 8
                Input { id: dedupeInput; width: parent.width - saveDedupe.width - 8; text: String(root.config.dedupeSeconds || 60); placeholderText: "Seconds"; inputMethodHints: Qt.ImhDigitsOnly }
                Pill { id: saveDedupe; label: "Save"; selected: true; enabled: !root.busy; onClicked: root.request("dedupe", [dedupeInput.text]) }
              }
            }
            Text { width: parent.width; wrapMode: Text.WordWrap; text: "Rules use Omarchy's crash watcher. Updating its ignore list briefly restarts that watcher; crashes during that instant may not notify. DND may allow critical and Omarchy action alerts."; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.bodySmall }
          }

          Rectangle {
            width: parent.width; height: 1; color: root.hairline
          }
          Row {
            width: parent.width; spacing: 8
            Text {
              width: parent.width - refreshButton.width - 8
              anchors.verticalCenter: parent.verticalCenter
              text: root.busy ? "Updating…" : root.notice || "Ready"
              textFormat: Text.PlainText
              color: root.noticeError ? Color.urgent : root.softInk
              font.family: root.face; font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }
            Pill { id: refreshButton; label: "󰑐  Refresh"; subtle: true; enabled: !root.busy; onClicked: root.request("read", []) }
          }
        }
      }
    }
  }

  component Pill: Rectangle {
    id: pill
    property string label: ""
    property bool selected: false
    property bool subtle: false
    signal clicked()
    width: pillText.implicitWidth + 24
    height: 29
    radius: 8
    color: selected ? root.tint : hover.hovered ? Qt.rgba(root.ink.r, root.ink.g, root.ink.b, 0.08) : "transparent"
    border.width: 1
    border.color: selected ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.48) : root.hairline
    opacity: enabled ? 1 : 0.38
    Behavior on color { ColorAnimation { duration: 130 } }
    Text {
      id: pillText
      anchors.centerIn: parent
      text: pill.label
      textFormat: Text.PlainText
      color: pill.selected ? Color.accent : root.ink
      font.family: root.face; font.pixelSize: Style.font.bodySmall
      font.bold: pill.selected
    }
    HoverHandler { id: hover }
    MouseArea { anchors.fill: parent; cursorShape: pill.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor; onClicked: if (pill.enabled) pill.clicked() }
  }

  component Input: QQC.TextField {
    id: input
    height: 32
    color: root.ink
    placeholderTextColor: root.softInk
    selectionColor: Color.accent
    selectedTextColor: Color.popups.background
    font.family: root.face
    font.pixelSize: Style.font.body
    leftPadding: 10; rightPadding: 10
    background: Rectangle {
      radius: 8
      color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, 0.055)
      border.width: 1
      border.color: input.activeFocus ? Color.accent : root.hairline
    }
  }

  component Card: Rectangle {
    id: card
    default property alias contents: cardColumn.data
    implicitHeight: cardColumn.implicitHeight + 28
    height: implicitHeight
    radius: Style.cornerRadius
    color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, 0.035)
    border.width: 1; border.color: root.hairline
    Column {
      id: cardColumn
      x: 14; y: 14
      width: card.width - 28
      spacing: 11
    }
  }

  component SectionHeading: Row {
    property string text: ""
    property string trailing: ""
    width: parent ? parent.width : 0
    height: Math.max(headingText.implicitHeight, trailingText.implicitHeight)
    Text { id: headingText; width: parent.width - trailingText.implicitWidth; text: parent.text; textFormat: Text.PlainText; color: root.ink; font.family: root.face; font.pixelSize: Style.font.title; font.bold: true; elide: Text.ElideRight }
    Text { id: trailingText; text: parent.trailing; textFormat: Text.PlainText; color: Color.accent; font.family: root.face; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1 }
  }

  component StatCard: Rectangle {
    property string label: ""
    property string value: ""
    property string detail: ""
    height: 78
    radius: Style.cornerRadius
    color: Qt.rgba(root.ink.r, root.ink.g, root.ink.b, 0.035)
    border.width: 1; border.color: root.hairline
    Column {
      anchors.left: parent.left; anchors.leftMargin: 12
      anchors.verticalCenter: parent.verticalCenter
      spacing: 3
      Text { text: parent.parent.label; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 0.8 }
      Text { text: parent.parent.value; color: root.ink; font.family: root.face; font.pixelSize: Style.font.heading; font.bold: true }
      Text { text: parent.parent.detail; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.caption }
    }
  }

  component CrashRow: Card {
    property var entry: ({})
    Row {
      width: parent.width; spacing: 8
      Column {
        width: parent.width - statusText.implicitWidth - 8; spacing: 4
        Text { text: entry.name || "Unknown process"; width: parent.width; elide: Text.ElideRight; color: root.ink; font.family: root.face; font.pixelSize: Style.font.title; font.bold: true }
        Text { text: (entry.count || 1) + " crash" + (entry.count === 1 ? "" : "es") + " · " + root.fmtTime(entry.timestamp); width: parent.width; elide: Text.ElideRight; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.bodySmall }
      }
      Text { id: statusText; text: entry.policy === "allowed" ? "ALLOWED" : "MUTED"; color: entry.policy === "allowed" ? root.softInk : Color.accent; font.family: root.face; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 0.8 }
    }
    Text { text: entry.policy === "allowed" ? "MUTE FOR" : "CHANGE MUTE"; color: root.softInk; font.family: root.face; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1 }
    Row {
      spacing: 6
      Repeater {
        model: root.muteDurations
        Pill { required property var modelData; label: modelData.label; enabled: !root.busy; onClicked: root.request("add", [entry.name, "silence", modelData.key, "All"]) }
      }
    }
  }
}

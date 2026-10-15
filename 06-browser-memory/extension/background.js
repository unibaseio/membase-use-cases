// Clicking the toolbar icon opens the side panel. Nothing else runs in the background:
// no storage, no key, no network.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((e) => console.error(e));

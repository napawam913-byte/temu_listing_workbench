const STORAGE_KEY = "compatSidepanelActivePanel";

const tabs = Array.from(document.querySelectorAll(".tab"));
const panels = Array.from(document.querySelectorAll(".panel"));
const panel1688Frame = document.querySelector("#panel1688 iframe");

for (const tab of tabs) {
  tab.addEventListener("click", () => {
    activatePanel(tab.dataset.panel);
  });
}

activatePanel(localStorage.getItem(STORAGE_KEY) || "panel1688");

if (chrome?.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type !== "active-tab-changed" || !message.is1688DetailPage) {
      return;
    }

    activatePanel("panel1688");
    panel1688Frame?.contentWindow?.postMessage(message, window.location.origin);
  });
}

function activatePanel(panelId) {
  for (const tab of tabs) {
    const isActive = tab.dataset.panel === panelId;
    tab.classList.toggle("is-active", isActive);
    tab.setAttribute("aria-selected", String(isActive));
  }

  for (const panel of panels) {
    panel.classList.toggle("is-active", panel.id === panelId);
  }

  localStorage.setItem(STORAGE_KEY, panelId);
}

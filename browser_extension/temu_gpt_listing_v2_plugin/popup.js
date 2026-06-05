document.getElementById("openDashboard").addEventListener("click", async () => {
  const url = chrome.runtime.getURL("dashboard.html");
  await chrome.tabs.create({ url });
  window.close();
});

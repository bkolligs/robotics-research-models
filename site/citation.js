document.getElementById("copy-citation").addEventListener("click", async () => {
  const status = document.getElementById("citation-status");
  const citation = document.getElementById("citation-text");
  status.textContent = "";
  try {
    await navigator.clipboard.writeText(citation.textContent);
    status.textContent = "Copied!";
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(citation);
    selection.removeAllRanges();
    selection.addRange(range);
    status.textContent = "Could not copy automatically. Copy the selected citation manually.";
  }
});

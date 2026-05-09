/**
 * 로컬 File 객체 미리보기(새 탭). RFP 첨부·컨설턴트 프로필 등 공통.
 */
(function () {
  function openAttachmentPreview(file) {
    const name = (file && file.name) || '';
    const mime = (file && file.type) || '';
    const textish =
      /^text\//i.test(mime) ||
      /(^|\.)(txt|log|md|csv|tsv|json|xml|yml|yaml|ini|env|sh|bat|cmd|sql|abap|properties|gitignore)$/i.test(
        name,
      );
    const maxText = 10 * 1024 * 1024;
    if (textish && file.size > 0 && file.size <= maxText) {
      const reader = new FileReader();
      reader.onload = () => {
        const blob = new Blob([reader.result], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        window.open(url, '_blank', 'noopener,noreferrer');
        window.setTimeout(() => URL.revokeObjectURL(url), 180000);
      };
      reader.onerror = () => {
        const url = URL.createObjectURL(file);
        window.open(url, '_blank', 'noopener,noreferrer');
        window.setTimeout(() => URL.revokeObjectURL(url), 180000);
      };
      reader.readAsText(file, 'UTF-8');
      return;
    }
    const url = URL.createObjectURL(file);
    window.open(url, '_blank', 'noopener,noreferrer');
    window.setTimeout(() => URL.revokeObjectURL(url), 180000);
  }

  window.openAttachmentPreview = openAttachmentPreview;
})();

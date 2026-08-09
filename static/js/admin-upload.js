/* white admin — drag & drop / click upload, shared by edit + media pages */
(function () {
  var UPLOAD_URL = document.body.getAttribute('data-upload-url') || '/admin/upload';
  var fileInput = document.getElementById('file-input');
  var drop = document.getElementById('dropzone');
  var feedback = document.getElementById('upload-feedback');
  var pendingTarget = null;

  function report(msg) {
    if (feedback) {
      feedback.textContent = msg;
      feedback.style.display = 'block';
    }
  }

  function upload(file, targetField) {
    if (!file) return;
    var fd = new FormData();
    fd.append('file', file);
    var folderEl = document.getElementById('upload-folder');
    if (folderEl && folderEl.value) fd.append('folder', folderEl.value);
    report('uploading ' + file.name + '…');
    fetch(UPLOAD_URL, { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { report('error: ' + d.error); return; }
        if (targetField) {
          var el = document.querySelector('[name="' + targetField + '"]');
          if (el) el.value = d.url;
        }
        if (typeof window.onUploaded === 'function') window.onUploaded(d);
        report('done → ' + d.url);
      })
      .catch(function () { report('upload failed'); });
  }

  if (!fileInput) return;

  document.querySelectorAll('.upload-pick-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      pendingTarget = btn.getAttribute('data-target');
      fileInput.value = '';
      fileInput.click();
    });
  });

  fileInput.addEventListener('change', function () {
    var f = this.files[0];
    if (f) upload(f, pendingTarget || null);
  });

  if (drop) {
    drop.addEventListener('dragover', function (e) { e.preventDefault(); drop.classList.add('over'); });
    drop.addEventListener('dragleave', function () { drop.classList.remove('over'); });
    drop.addEventListener('drop', function (e) {
      e.preventDefault();
      drop.classList.remove('over');
      var f = e.dataTransfer.files[0];
      if (f) upload(f, pendingTarget || null);
    });
    drop.addEventListener('click', function () { pendingTarget = null; fileInput.click(); });
  }
})();

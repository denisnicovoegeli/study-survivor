// UploadModal.jsx: Dialog zum Hochladen ganzer Ordner mit Unterordnern (T6)
import React from "react";
import { useStudio } from "../app/store.jsx";
import { Icon } from "../ui/Icon.jsx";
import "./upload.css";

const { useState, useRef, useMemo } = React;

const ALLOWED_EXTS = new Set([".pdf", ".pptx", ".docx", ".xlsx"]);
const MAX_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB

// Rekursives Auslesen von Verzeichnissen ueber webkitGetAsEntry
async function scanEntry(entry, path = "") {
  if (entry.isFile) {
    const file = await new Promise((resolve) => entry.file(resolve));
    return [{ file, relPath: path ? `${path}/${file.name}` : file.name }];
  }
  if (entry.isDirectory) {
    const reader = entry.createReader();
    const entries = await new Promise((resolve) => reader.readEntries(resolve));
    const results = [];
    for (const child of entries) {
      const sub = await scanEntry(child, path ? `${path}/${entry.name}` : entry.name);
      results.push(...sub);
    }
    return results;
  }
  return [];
}

export function UploadModal({ isOpen, onClose }) {
  const { courses, course: activeCourse, reloadTree, toast } = useStudio();

  const [targetCourse, setTargetCourse] = useState(
    () => (typeof activeCourse === "string" ? activeCourse : activeCourse?.name || courses[0]?.name || courses[0] || "")
  );

  const [fileList, setFileList] = useState([]); // [{ file, relPath }]
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);

  const folderInputRef = useRef(null);
  const filesInputRef = useRef(null);

  // Gesamtgroesse berechnen
  const totalBytes = useMemo(() => {
    return fileList.reduce((sum, item) => sum + (item.file?.size || 0), 0);
  }, [fileList]);

  const totalMb = (totalBytes / (1024 * 1024)).toFixed(1);
  const isTooLarge = totalBytes > MAX_SIZE_BYTES;

  // Erlaubte vs. uebersprungene Dateien
  const { allowedFiles, skippedFiles } = useMemo(() => {
    const allowed = [];
    const skipped = [];
    for (const item of fileList) {
      const ext = item.file.name.slice(item.file.name.lastIndexOf(".")).toLowerCase();
      if (ALLOWED_EXTS.has(ext)) {
        allowed.push(item);
      } else {
        skipped.push({ ...item, ext });
      }
    }
    return { allowedFiles: allowed, skippedFiles: skipped };
  }, [fileList]);

  // Drag and Drop Ereignisse
  const handleDragOver = (e) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setDragOver(false);
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    setDragOver(false);
    setResult(null);

    const items = e.dataTransfer.items;
    if (!items || items.length === 0) return;

    const scanned = [];
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.webkitGetAsEntry) {
        const entry = item.webkitGetAsEntry();
        if (entry) {
          const res = await scanEntry(entry);
          scanned.push(...res);
        }
      } else if (item.getAsFile) {
        const file = item.getAsFile();
        if (file) scanned.push({ file, relPath: file.name });
      }
    }

    setFileList((prev) => [...prev, ...scanned]);
  };

  // Ordner-Auswahl ueber File-Picker mit webkitdirectory
  const handleFolderSelect = (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    setResult(null);

    const mapped = files.map((f) => ({
      file: f,
      relPath: f.webkitRelativePath || f.name,
    }));
    setFileList((prev) => [...prev, ...mapped]);
    e.target.value = "";
  };

  // Normale Datei-Auswahl
  const handleFilesSelect = (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    setResult(null);

    const mapped = files.map((f) => ({
      file: f,
      relPath: f.name,
    }));
    setFileList((prev) => [...prev, ...mapped]);
    e.target.value = "";
  };

  // Upload durchfuehren
  const handleUpload = async () => {
    if (!targetCourse) {
      toast("Bitte einen Kurs auswählen.");
      return;
    }
    if (allowedFiles.length === 0) {
      toast("Keine erlaubten Dateien (.pdf, .pptx, .docx, .xlsx) zum Hochladen vorhanden.");
      return;
    }
    if (isTooLarge) {
      toast("Gesamtgrösse überschreitet das Limit von 50 MB.");
      return;
    }

    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("course", targetCourse);

      for (const item of allowedFiles) {
        fd.append("files", item.file);
        fd.append("paths", item.relPath);
      }

      const SDK = window.__HERMES_PLUGIN_SDK__;
      const fetchFn = SDK?.authedFetch || window.fetch;
      const res = await fetchFn("/api/plugins/studium/kurse/upload-folder", {
        method: "POST",
        body: fd,
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      }

      setResult({
        saved: data.saved || [],
        skipped: [...skippedFiles, ...(data.skipped || [])],
        saved_count: data.saved_count || 0,
      });

      setFileList([]);
      toast(`${data.saved_count || allowedFiles.length} Dateien erfolgreich hochgeladen.`);
      if (typeof reloadTree === "function") {
        await reloadTree();
      }
    } catch (err) {
      toast("Fehler beim Hochladen: " + (err.message || String(err)));
    } finally {
      setUploading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="stu-modal-backdrop"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="stu-modal"
        style={{ maxWidth: "560px", width: "100%" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="stu-modal-head">
          <h3>Ordner hochladen</h3>
          <button
            type="button"
            className="stu-icbtn"
            onClick={onClose}
            aria-label="Dialog schliessen"
          >
            <Icon n="x" />
          </button>
        </div>

        <div className="stu-modal-body">
          {/* Kursauswahl */}
          <div className="stu-form-group">
            <label htmlFor="upload-course">Zielkurs</label>
            <select
              id="upload-course"
              className="stu-select"
              value={targetCourse}
              onChange={(e) => setTargetCourse(e.target.value)}
              disabled={uploading}
            >
              <option value="" disabled>
                Kurs auswählen …
              </option>
              {courses.map((c) => {
                const name = typeof c === "string" ? c : c.name;
                return (
                  <option key={name} value={name}>
                    {name}
                  </option>
                );
              })}
            </select>
          </div>

          {/* Ergebnis-Ansicht nach erfolgreichem Upload */}
          {result ? (
            <div style={{ display: "grid", gap: "12px" }}>
              <div
                style={{
                  background: "rgba(40, 167, 69, 0.1)",
                  border: "1px solid rgba(40, 167, 69, 0.3)",
                  borderRadius: "8px",
                  padding: "12px 14px",
                  fontSize: "13px",
                }}
              >
                <b>{result.saved_count} Dateien erfolgreich abgelegt</b>
                <div style={{ marginTop: "4px", color: "var(--muted)", fontSize: "12px" }}>
                  Die Dokumente sind nun im Explorer unter „Eigene“ verfügbar.
                </div>
              </div>

              {result.skipped && result.skipped.length > 0 && (
                <div>
                  <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
                    Übersprungene Dateien (nicht erlaubte Endungen):
                  </span>
                  <div className="stu-upload-filelist" style={{ marginTop: "4px" }}>
                    {result.skipped.map((s, idx) => (
                      <div key={idx} className="stu-upload-fileitem is-skipped">
                        <span className="stu-upload-filepath">{s.relPath || s.path}</span>
                        <span className="stu-upload-tag-skipped">
                          {s.reason || "Format nicht erlaubt"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="stu-modal-foot">
                <button
                  type="button"
                  className="stu-tbtn"
                  onClick={() => setResult(null)}
                >
                  Weitere hochladen
                </button>
                <button
                  type="button"
                  className="stu-tbtn is-pri"
                  onClick={onClose}
                >
                  Fertig
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Dropzone */}
              <div
                className={`stu-upload-dropzone ${dragOver ? "is-dragover" : ""}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => folderInputRef.current?.click()}
              >
                <Icon n="upload" className="stu-upload-dropzone-icon" />
                <div className="stu-upload-dropzone-title">
                  Ordner hierhin ziehen oder klicken
                </div>
                <div className="stu-upload-dropzone-desc">
                  Unterordner bleiben erhalten · Erlaubt: .pdf, .pptx, .docx, .xlsx (max. 50 MB)
                </div>

                <div style={{ display: "flex", gap: "8px", marginTop: "6px" }} onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    className="stu-tbtn"
                    onClick={() => folderInputRef.current?.click()}
                  >
                    Ordner wählen
                  </button>
                  <button
                    type="button"
                    className="stu-tbtn"
                    onClick={() => filesInputRef.current?.click()}
                  >
                    Dateien wählen
                  </button>
                </div>

                {/* Versteckte File-Inputs */}
                <input
                  ref={folderInputRef}
                  type="file"
                  webkitdirectory=""
                  directory=""
                  multiple
                  style={{ display: "none" }}
                  onChange={handleFolderSelect}
                />
                <input
                  ref={filesInputRef}
                  type="file"
                  multiple
                  style={{ display: "none" }}
                  onChange={handleFilesSelect}
                />
              </div>

              {/* Ausgewaehlte Dateien */}
              {fileList.length > 0 && (
                <div style={{ display: "grid", gap: "6px" }}>
                  <div className="stu-upload-summary">
                    <span>{fileList.length} Dateien ausgewählt ({allowedFiles.length} gültig, {skippedFiles.length} übersprungen)</span>
                    <span className={isTooLarge ? "stu-upload-size-warn" : ""}>
                      {totalMb} MB / 50 MB
                    </span>
                  </div>

                  {isTooLarge && (
                    <div className="stu-error-box" style={{ padding: "8px 12px", fontSize: "12px" }}>
                      Gesamtgrösse überschreitet das Limit von 50 MB. Bitte weniger Dateien auswählen.
                    </div>
                  )}

                  <div className="stu-upload-filelist">
                    {fileList.map((item, idx) => {
                      const ext = item.file.name.slice(item.file.name.lastIndexOf(".")).toLowerCase();
                      const isAllowed = ALLOWED_EXTS.has(ext);
                      const sizeKb = (item.file.size / 1024).toFixed(0);

                      return (
                        <div
                          key={idx}
                          className={`stu-upload-fileitem ${!isAllowed ? "is-skipped" : ""}`}
                        >
                          <span className="stu-upload-filepath" title={item.relPath}>
                            {item.relPath}
                          </span>
                          <span className="stu-upload-filesize">{sizeKb} KB</span>
                          {!isAllowed && (
                            <span className="stu-upload-tag-skipped">
                              Übersprungen ({ext || "ohne Endung"})
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="stu-modal-foot">
                {fileList.length > 0 && (
                  <button
                    type="button"
                    className="stu-tbtn"
                    onClick={() => setFileList([])}
                    disabled={uploading}
                    style={{ marginRight: "auto" }}
                  >
                    Liste leeren
                  </button>
                )}

                <button
                  type="button"
                  className="stu-tbtn"
                  onClick={onClose}
                  disabled={uploading}
                >
                  Abbrechen
                </button>

                <button
                  type="button"
                  className="stu-tbtn is-pri"
                  onClick={handleUpload}
                  disabled={uploading || allowedFiles.length === 0 || isTooLarge}
                >
                  {uploading
                    ? "Wird hochgeladen …"
                    : `Hochladen (${allowedFiles.length} ${allowedFiles.length === 1 ? "Datei" : "Dateien"})`}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default UploadModal;

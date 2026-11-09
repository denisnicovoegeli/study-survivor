// CodeMirror-6-Editor fuer Markdown (ohne @codemirror/language-data: IIFE kennt
// keine Code-Splits, alle Sprachen wuerden inline landen).
import { EditorView, basicSetup } from "codemirror";
import { Compartment, EditorState } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { markdown } from "@codemirror/lang-markdown";

// Erstellt einen Editor in `parent`.
//   doc       Anfangstext
//   readOnly  schreibgeschuetzt (Moodle, nicht bearbeitbare Dateien)
//   onChange  (text) => void, bei jeder Aenderung
//   onSave    (text) => void, bei Mod-S
// Liefert {view, getText, setText, setReadOnly, isDirty, markClean, focus, destroy}.
export function createEditor({ parent, doc = "", readOnly = false, onChange, onSave } = {}) {
  const readOnlyConf = new Compartment();
  let cleanDoc = doc;

  const readOnlyExt = (ro) => [EditorState.readOnly.of(ro), EditorView.editable.of(!ro)];

  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc,
      extensions: [
        keymap.of([{
          key: "Mod-s",
          preventDefault: true,
          run: (v) => {
            onSave?.(v.state.doc.toString());
            return true;
          },
        }]),
        basicSetup,
        markdown(),
        EditorView.lineWrapping,
        readOnlyConf.of(readOnlyExt(readOnly)),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) onChange?.(u.state.doc.toString());
        }),
      ],
    }),
  });

  return {
    view,
    getText: () => view.state.doc.toString(),
    // Ersetzt den ganzen Inhalt (z. B. nach Neuladen oder Wiederherstellen) und gilt als gespeichert.
    setText(text) {
      cleanDoc = text;
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
    },
    setReadOnly: (ro) => view.dispatch({ effects: readOnlyConf.reconfigure(readOnlyExt(ro)) }),
    isDirty: () => view.state.doc.toString() !== cleanDoc,
    markClean(text) {
      cleanDoc = text ?? view.state.doc.toString();
    },
    // Markierter Text (leer, wenn nichts markiert ist).
    selection() {
      const { from, to } = view.state.selection.main;
      return view.state.sliceDoc(from, to);
    },
    focus: () => view.focus(),
    destroy: () => view.destroy(),
  };
}

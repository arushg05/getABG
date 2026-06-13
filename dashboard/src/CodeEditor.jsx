import { useRef, useEffect } from "react";

export default function CodeEditor({ value, onChange }) {
  const editorRef = useRef(null);
  const cmInstance = useRef(null);

  useEffect(() => {
    if (editorRef.current && !cmInstance.current && window.CodeMirror) {
      cmInstance.current = window.CodeMirror(editorRef.current, {
        value: value || "",
        mode: "python",
        theme: "dracula",
        lineNumbers: true,
        indentUnit: 4,
        matchBrackets: true,
      });

      cmInstance.current.setSize("100%", "400px");

      cmInstance.current.on("change", (instance) => {
        if (onChange) {
          onChange(instance.getValue());
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (cmInstance.current && value !== cmInstance.current.getValue()) {
      cmInstance.current.setValue(value);
    }
  }, [value]);

  return (
    <div
      ref={editorRef}
      style={{
        width: "100%",
        border: "1px solid var(--color-border-tertiary)",
        borderRadius: "var(--border-radius-md)",
        overflow: "hidden",
        fontSize: "13px",
        height: "400px", // scrollable explicitly via CodeMirror css
        textAlign: "left"
      }}
    />
  );
}

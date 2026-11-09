// ErrorBoundary.jsx: faengt Renderfehler einer Teilansicht ab, damit nicht das ganze Dashboard leer wird
import React from "react";

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
    this.reset = this.reset.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Fuer die Fehlersuche in der Browser-Konsole
    console.error(`[studium] Fehler in ${this.props.name || "Ansicht"}:`, error, info?.componentStack);
  }

  componentDidUpdate(prevProps) {
    // Beim Wechsel der Ansicht (resetKey) neu versuchen
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  reset() {
    this.setState({ error: null });
    this.props.onReset?.();
  }

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.silent) return null;
    const box = (
      <div className="stu-errbox" role="alert">
        <div className="stu-errbox-t">{this.props.name || "Diese Ansicht"} ist abgestürzt.</div>
        <div className="stu-errbox-m">{String(this.state.error?.message || this.state.error)}</div>
        <button type="button" className="stu-tbtn" onClick={this.reset}>
          {this.props.onReset ? "Schliessen" : "Erneut versuchen"}
        </button>
      </div>
    );
    // Fehler in einem Fenster: als Overlay anzeigen statt im Layout
    return this.props.overlay ? <div className="stu-errbox-overlay">{box}</div> : box;
  }
}

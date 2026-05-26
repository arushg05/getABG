/**
 * getABG — Upgrade Page
 * Pricing comparison and Razorpay checkout integration.
 */

import { useState } from "react";
import { useAuth } from "./useAuth.jsx";

const getApiUrl = () => {
  let base = (import.meta.env.VITE_API_URL || "http://localhost:5050/api").replace(/\/+$/, "");
  return base.endsWith("/api") ? base : `${base}/api`;
};
const API = getApiUrl();

function PlanFeature({ text, included = true, highlight = false }) {
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 8,
      fontSize: 12,
      color: included ? "var(--color-text-secondary)" : "var(--color-text-tertiary)",
      padding: "4px 0",
    }}>
      <span style={{
        fontSize: 13,
        color: included
          ? (highlight ? "var(--color-text-info)" : "var(--color-text-success)")
          : "var(--color-text-tertiary)",
        fontWeight: 600,
        width: 18,
        textAlign: "center",
      }}>
        {included ? "✓" : "—"}
      </span>
      <span style={{
        fontWeight: highlight ? 500 : 400,
        color: highlight ? "var(--color-text-primary)" : undefined,
      }}>{text}</span>
    </div>
  );
}

export default function UpgradePage({ onClose }) {
  const { user, authFetch, refreshUser, isPro } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  const handleUpgrade = async () => {
    setLoading(true);
    setError(null);

    try {
      // 1. Create Razorpay order
      const orderResp = await authFetch(`${API}/payments/create-order`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      const orderData = await orderResp.json();
      if (!orderResp.ok) throw new Error(orderData.error || "Failed to create order");

      // 2. Load Razorpay checkout script if not already loaded
      await loadRazorpayScript();

      // 3. Open Razorpay checkout modal
      const options = {
        key: orderData.key_id,
        amount: orderData.amount,
        currency: orderData.currency,
        name: "getABG",
        description: "Pro Plan — Unlimited Backtests",
        order_id: orderData.order_id,
        prefill: {
          email: user?.email || "",
        },
        theme: {
          color: "#38BDF8",
          backdrop_color: "rgba(15,23,42,0.85)",
        },
        modal: {
          ondismiss: () => setLoading(false),
        },
        handler: async (response) => {
          // 4. Verify payment
          try {
            const verifyResp = await authFetch(`${API}/payments/verify`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
              }),
            });

            const verifyData = await verifyResp.json();
            if (!verifyResp.ok) throw new Error(verifyData.error || "Verification failed");

            setSuccess(true);
            await refreshUser(); // Refresh user state to reflect Pro plan
          } catch (err) {
            setError(err.message);
          } finally {
            setLoading(false);
          }
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.on("payment.failed", (response) => {
        setError(response.error?.description || "Payment failed. Please try again.");
        setLoading(false);
      });
      rzp.open();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.9)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        backdropFilter: "blur(8px)",
      }}>
        <div style={{
          background: "var(--color-background-secondary)",
          border: "0.5px solid var(--color-border-success)",
          borderRadius: "var(--border-radius-lg)",
          padding: "40px 32px",
          textAlign: "center",
          maxWidth: 380,
          boxShadow: "0 16px 48px rgba(0,0,0,0.4)",
          animation: "fadeIn 0.3s ease",
        }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🎉</div>
          <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>Welcome to Pro!</div>
          <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 24, lineHeight: 1.6 }}>
            You now have unlimited backtests. Go build some alpha.
          </div>
          <button
            onClick={onClose}
            style={{
              padding: "10px 28px",
              fontSize: 13,
              fontWeight: 500,
              borderRadius: "var(--border-radius-md)",
              border: "none",
              background: "linear-gradient(135deg, #38BDF8, #818CF8)",
              color: "#fff",
              cursor: "pointer",
            }}
          >
            Start Backtesting
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      position: "fixed",
      inset: 0,
      background: "rgba(15,23,42,0.9)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: 1000,
      backdropFilter: "blur(8px)",
      padding: "1rem",
    }}>
      <div style={{
        width: "100%",
        maxWidth: 680,
        position: "relative",
      }}>
        {/* Close button */}
        <button
          onClick={onClose}
          style={{
            position: "absolute",
            top: -40,
            right: 0,
            background: "none",
            border: "none",
            color: "var(--color-text-tertiary)",
            fontSize: 14,
            cursor: "pointer",
            padding: "4px 8px",
          }}
        >
          ✕ Close
        </button>

        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em" }}>
            Choose Your Plan
          </div>
          <div style={{ fontSize: 13, color: "var(--color-text-tertiary)", marginTop: 4 }}>
            Unlock unlimited backtesting power
          </div>
        </div>

        {/* Plan Cards Grid */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
        }}>
          {/* Free Plan */}
          <div style={{
            background: "var(--color-background-secondary)",
            border: "0.5px solid var(--color-border-tertiary)",
            borderRadius: "var(--border-radius-lg)",
            padding: "24px 20px",
            display: "flex",
            flexDirection: "column",
            boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
          }}>
            <div style={{
              fontSize: 10,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              color: "var(--color-text-tertiary)",
              marginBottom: 6,
            }}>Free</div>

            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginBottom: 16 }}>
              <span style={{ fontSize: 32, fontWeight: 700 }}>₹0</span>
              <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>/forever</span>
            </div>

            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2, marginBottom: 20 }}>
              <PlanFeature text="3 backtests per day" />
              <PlanFeature text="All built-in strategies" />
              <PlanFeature text="Custom strategy upload" />
              <PlanFeature text="Basic performance metrics" />
              <PlanFeature text="Equity curve charts" />
              <PlanFeature text="Unlimited backtests" included={false} />
              <PlanFeature text="Priority execution" included={false} />
              <PlanFeature text="Export reports" included={false} />
            </div>

            <button
              disabled
              style={{
                padding: "10px 0",
                fontSize: 12,
                fontWeight: 500,
                borderRadius: "var(--border-radius-md)",
                border: "0.5px solid var(--color-border-tertiary)",
                background: "var(--color-background-primary)",
                color: "var(--color-text-tertiary)",
                cursor: "default",
              }}
            >
              Current Plan
            </button>
          </div>

          {/* Pro Plan */}
          <div style={{
            background: "var(--color-background-secondary)",
            border: "1px solid rgba(56,189,248,0.3)",
            borderRadius: "var(--border-radius-lg)",
            padding: "24px 20px",
            display: "flex",
            flexDirection: "column",
            position: "relative",
            boxShadow: "0 4px 24px rgba(56,189,248,0.1), 0 8px 32px rgba(0,0,0,0.3)",
          }}>
            {/* Popular badge */}
            <div style={{
              position: "absolute",
              top: -10,
              right: 16,
              background: "linear-gradient(135deg, #38BDF8, #818CF8)",
              color: "#fff",
              fontSize: 9,
              fontWeight: 600,
              padding: "3px 10px",
              borderRadius: 20,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              boxShadow: "0 2px 8px rgba(56,189,248,0.3)",
            }}>
              POPULAR
            </div>

            <div style={{
              fontSize: 10,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              color: "var(--color-text-info)",
              marginBottom: 6,
            }}>Pro</div>

            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginBottom: 4 }}>
              <span style={{ fontSize: 32, fontWeight: 700 }}>₹1,599</span>
              <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>/month</span>
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 16 }}>
              ≈ $19 USD · Cancel anytime
            </div>

            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2, marginBottom: 20 }}>
              <PlanFeature text="Unlimited backtests" highlight />
              <PlanFeature text="All built-in strategies" />
              <PlanFeature text="Custom strategy upload" />
              <PlanFeature text="Full performance metrics" />
              <PlanFeature text="Equity curve charts" />
              <PlanFeature text="Priority execution queue" highlight />
              <PlanFeature text="Export PDF reports" highlight />
              <PlanFeature text="Email support" />
            </div>

            {isPro ? (
              <button
                disabled
                style={{
                  padding: "10px 0",
                  fontSize: 12,
                  fontWeight: 500,
                  borderRadius: "var(--border-radius-md)",
                  border: "1px solid var(--color-border-success)",
                  background: "var(--color-background-success)",
                  color: "var(--color-text-success)",
                  cursor: "default",
                }}
              >
                ✓ Active
              </button>
            ) : (
              <button
                onClick={handleUpgrade}
                disabled={loading}
                style={{
                  padding: "11px 0",
                  fontSize: 13,
                  fontWeight: 600,
                  borderRadius: "var(--border-radius-md)",
                  border: "none",
                  background: "linear-gradient(135deg, #38BDF8, #818CF8)",
                  color: "#fff",
                  cursor: loading ? "wait" : "pointer",
                  opacity: loading ? 0.7 : 1,
                  transition: "opacity 0.2s, transform 0.1s",
                  boxShadow: "0 2px 12px rgba(56,189,248,0.3)",
                }}
              >
                {loading ? "Processing…" : "Upgrade to Pro"}
              </button>
            )}
          </div>
        </div>

        {error && (
          <div style={{
            marginTop: 16,
            background: "var(--color-background-danger)",
            color: "var(--color-text-danger)",
            borderRadius: "var(--border-radius-md)",
            padding: "10px 14px",
            fontSize: 12,
            textAlign: "center",
          }}>
            {error}
          </div>
        )}

        {/* Trust signals */}
        <div style={{
          marginTop: 20,
          textAlign: "center",
          fontSize: 11,
          color: "var(--color-text-tertiary)",
          display: "flex",
          justifyContent: "center",
          gap: 16,
        }}>
          <span>🔒 Secure payment via Razorpay</span>
          <span>💳 UPI / Cards / NetBanking</span>
          <span>↩ Cancel anytime</span>
        </div>
      </div>
    </div>
  );
}

// ── Razorpay Script Loader ───────────────────────────────────────────────────

let razorpayLoaded = false;

function loadRazorpayScript() {
  return new Promise((resolve, reject) => {
    if (razorpayLoaded || window.Razorpay) {
      razorpayLoaded = true;
      return resolve();
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => {
      razorpayLoaded = true;
      resolve();
    };
    script.onerror = () => reject(new Error("Failed to load Razorpay checkout"));
    document.body.appendChild(script);
  });
}

(function () {
    const wsUrl =
      (location.protocol === "https:" ? "wss://" : "ws://") +
      location.host +
      `/ws/staff`;
  
    const ws = new WebSocket(wsUrl);
  
    ws.onopen = () => {
      try { ws.send("hi"); } catch (_) {}
    };
  
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        console.log("STAFF WS:", msg);
  
        // ✅ ออเดอร์ใหม่
        if (msg.type === "new_order" || msg.type === "order_created") {
          location.reload();
          return;
        }
  
        // ✅ payment update
        if (msg.type === "payment_update") {
          const badge = document.getElementById(`pay-${msg.order_id}`);
          if (badge) {
            badge.textContent = msg.payment_status || "unpaid";
            badge.className =
              "badge " + (msg.payment_status === "paid" ? "text-bg-success" : "text-bg-warning");
          }
          return;
        }
  
        // ✅ order status
        if (msg.type === "order_status") {
          const el = document.getElementById(`order-status-${msg.order_id}`);
          if (el) el.textContent = msg.order_status || "new";
          return;
        }
  
      } catch (e) {
        // console.log("STAFF WS RAW:", ev.data);
      }
    };
  
    ws.onclose = () => console.log("STAFF WS closed");
    ws.onerror = (err) => console.log("STAFF WS error", err);
  
    // ✅ ทำให้ปุ่ม confirm ใช้งานได้จริง
    window.confirmPayment = async function (orderId) {
      if (!confirm("ยืนยันว่าชำระเงินแล้วใช่ไหม?")) return;
    
      const btn = document.getElementById(`btn-pay-${orderId}`);
    
      if (btn) {
        btn.disabled = true;
        btn.dataset.oldText = btn.textContent;
        btn.textContent = "กำลังยืนยัน...";
      }
    
      try {
        const res = await fetch(`/staff/orders/${orderId}/notify_payment`, {
          method: "POST",
        });
    
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t || "ยืนยันการชำระเงินไม่สำเร็จ");
        }
    
        // ✅ อัปเดต badge
        const badge = document.getElementById(`pay-${orderId}`);
        if (badge) {
          badge.textContent = "paid";
          badge.className = "badge text-bg-success";
        }
    
        // ✅ เปลี่ยนปุ่มเป็น Paid
        if (btn) {
          btn.textContent = "Paid ✅";
          btn.classList.remove("btn-success");
          btn.classList.add("btn-secondary");
          btn.disabled = true;
        }
    
      } catch (err) {
        alert("เชื่อมต่อไม่สำเร็จ: " + (err?.message || err));
        if (btn) {
          btn.disabled = false;
          btn.textContent = btn.dataset.oldText || "confirm payment";
        }
      }
    };
    
  })();
  
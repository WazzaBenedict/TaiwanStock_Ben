/**
 * 台股監測工具 V10.3 TradingView Edition
 *
 * ★ Firebase Console 必要設定：
 *   1. Authentication → Sign-in methods → 啟用 Google Provider
 *   2. Authentication → Authorized domains → 加入 taiwanstock-ben.web.app
 *   3. Firestore → Rules → 確保 users/{uid} 只允許對應 uid 讀寫
 */
window.API_BASE_URL = "https://taiwanstock-ben-1.onrender.com";

window.FIREBASE_CONFIG = {
  apiKey: "AIzaSyAr_msYm9k1twrCMtsALwBY-z1dY4lMtkI",
  authDomain: "taiwanstock-ben.firebaseapp.com",
  databaseURL: "https://taiwanstock-ben-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "taiwanstock-ben",
  storageBucket: "taiwanstock-ben.firebasestorage.app",
  messagingSenderId: "1084691510550",
  appId: "1:1084691510550:web:4a2350939d209bb8888c37"
};

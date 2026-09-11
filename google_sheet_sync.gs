/**
 * ============================================================================
 * GIC LOGISTICS - GOOGLE APPS SCRIPT SYNC DÒNG TIỀN TẠM ỨNG GIDO
 * ============================================================================
 * Không cần mở Google Sheet, không cần ấn nút "Tiện ích mở rộng (Extensions)".
 * Script này có thể chạy độc lập (Standalone Script tại script.new hoặc script.google.com).
 * 
 * CÁCH DÙNG:
 * 1. Truy cập https://script.new
 * 2. Dán toàn bộ nội dung file này vào.
 * 3. Điền RENDER_URL của bạn (nếu có).
 * 4. Chạy hàm `installTriggerWithoutExtension()` ➔ Xong! 
 *    Hệ thống sẽ tự động bắt sự kiện khi Google Sheet thay đổi và bắn Webhook 24/7.
 * ============================================================================
 */

// CẤU HÌNH THÔNG TIN GOOGLE SHEET & WEBHOOK
var GIDO_SPREADSHEET_ID = '1ZZC5hnoRRo93Fc3AH-mcKCu692xRhX6Zy04ENhiz6p8';
var GIDO_SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1ZZC5hnoRRo93Fc3AH-mcKCu692xRhX6Zy04ENhiz6p8/edit';

// URL web server Render của bạn (thay bằng domain Render thực tế của bạn)
var RENDER_URL = 'https://gic-logistics.onrender.com';
var WEBHOOK_SECRET = 'gic-secret-2026';

// DANH SÁCH TẤT CẢ CÁC TRƯỜNG DỮ LIỆU CỦA GOOGLE SHEET
var SHEET_FIELDS = [
  { col: 0,  name: 'trans_date',          label: 'NGÀY' },
  { col: 1,  name: 'content',             label: 'NỘI DUNG' },
  // Nhóm Tuấn
  { col: 2,  name: 'tuan_ton',            label: 'TUẤN - Tồn' },
  { col: 3,  name: 'tuan_thu_cty',        label: 'TUẤN - Thu từ Công ty' },
  { col: 4,  name: 'tuan_thu_haiban',     label: 'TUẤN - Thu từ Hải Bân' },
  { col: 5,  name: 'tuan_thu_khac',       label: 'TUẤN - Thu khác / Hoàn ứng' },
  { col: 6,  name: 'tuan_chi_haiban_cty', label: 'TUẤN - Chi nộp tiền Hải Bân về công ty' },
  { col: 7,  name: 'tuan_chi',            label: 'TUẤN - Chi tạm ứng' },
  // Nhân sự khác
  { col: 8,  name: 'xuyen_amount',        label: 'XUYÊN' },
  { col: 9,  name: 'luong_thu',           label: 'LƯƠNG - Thu' },
  { col: 10, name: 'luong_chi',           label: 'LƯƠNG - Chi' },
  { col: 11, name: 'truong_amount',       label: 'TRƯỜNG' },
  // Đối tác & Chứng từ
  { col: 12, name: 'partner_amount',      label: 'ĐỐI TÁC' },
  { col: 13, name: 'partner_invoice',     label: 'HÓA ĐƠN ĐỐI TÁC' },
  { col: 14, name: 'bill_link',           label: 'LINK BILL CK' },
  { col: 15, name: 'advance_refund',      label: 'HOÀN ỨNG' },
  { col: 16, name: 'accounting_status',   label: 'KẾ TOÁN THANH TOÁN' }
];

/**
 * HÀM 1: Cài đặt Trigger tự động 1-Click (KHÔNG CẦN BẤM EXTENSION)
 * Chạy hàm này một lần duy nhất từ script.new hoặc Script Console.
 * Nó sẽ tự kết nối vào Google Sheet qua GIDO_SPREADSHEET_ID và gắn trigger onChange.
 */
function installTriggerWithoutExtension() {
  var ss = SpreadsheetApp.openById(GIDO_SPREADSHEET_ID);
  
  // Xóa các trigger cũ nếu đã có để tránh trùng lặp
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === 'handleSpreadsheetChange') {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  
  // Tạo Trigger tự động khi Google Sheet thay đổi (OnChange)
  ScriptApp.newTrigger('handleSpreadsheetChange')
    .forSpreadsheet(ss)
    .onChange()
    .create();
    
  Logger.log('✅ ĐÃ KÍCH HOẠT THÀNH CÔNG TRIGGER TỰ ĐỘNG CHO GOOGLE SHEET: ' + GIDO_SPREADSHEET_ID);
  Logger.log('Từ bây giờ: Bất kỳ ai sửa Google Sheet, hệ thống sẽ tự động cập nhật lên Render mà không cần mở extension hay bật máy tính!');
}

/**
 * HÀM 2: Hàm xử lý khi có bất kỳ thay đổi nào trên Google Sheet
 * Được Google Cloud tự động gọi 24/7 khi có người sửa ô, thêm dòng.
 */
function handleSpreadsheetChange(e) {
  var ss = SpreadsheetApp.openById(GIDO_SPREADSHEET_ID);
  var activeSheet = ss.getActiveSheet();
  var sheetName = activeSheet.getName();
  
  Logger.log('Phát hiện cập nhật trên sheet: ' + sheetName);
  
  // Phân tích tháng và năm từ tên sheet (VD: "Tháng 08-2026")
  var month = 8;
  var year = 2026;
  var match = sheetName.match(/Tháng\s*(\d+)-(\d+)/i);
  if (match) {
    month = parseInt(match[1], 10);
    year = parseInt(match[2], 10);
  }
  
  sendWebhookToRender(month, year);
}

/**
 * HÀM 3: Gửi tín hiệu Webhook sang Render để cập nhật tức thì
 */
function sendWebhookToRender(month, year) {
  var webhookUrl = RENDER_URL + '/advances/webhook?secret=' + encodeURIComponent(WEBHOOK_SECRET) +
                   '&month=' + encodeURIComponent(month) +
                   '&year=' + encodeURIComponent(year);
                   
  Logger.log('Đang gửi Webhook tới: ' + webhookUrl);
  
  try {
    var options = {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({
        spreadsheetId: GIDO_SPREADSHEET_ID,
        month: month,
        year: year,
        timestamp: new Date().toISOString()
      }),
      muteHttpExceptions: true
    };
    
    var response = UrlFetchApp.fetch(webhookUrl, options);
    Logger.log('Kết quả Webhook từ Render: ' + response.getResponseCode() + ' | ' + response.getContentText());
  } catch (err) {
    Logger.log('Lỗi gửi Webhook: ' + err.message);
  }
}

/**
 * HÀM 4: Test thủ công ngay lập tức
 * Bấm chạy hàm này để thử đồng bộ Tháng 8/2026 sang Render ngay lập tức.
 */
function testSyncManual() {
  sendWebhookToRender(8, 2026);
}

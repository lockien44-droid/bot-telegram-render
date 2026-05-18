"""
Backup & Recovery Manager cho Google Sheets
"""

import os
import json
import gzip
import shutil
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import gspread
from google.oauth2.service_account import Credentials
import logging


class BackupManager:
    """Quản lý backup cho Google Sheets"""
    
    def __init__(
        self,
        gsheet_id: str,
        gsvc_json: str,
        backup_dir: str = "backups"
    ):
        self.gsheet_id = gsheet_id
        self.gsvc_json = gsvc_json
        self.backup_dir = backup_dir
        
        # Create backup directory
        os.makedirs(backup_dir, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Initialize Google Sheets client
        self._init_gsheet()
    
    def _init_gsheet(self):
        """Initialize Google Sheets client"""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        
        # Kiểm tra xem có biến môi trường không
        json_content = os.getenv("GOOGLE_JSON_CONTENT")
        
        if json_content:
            # Nạp từ environment variable
            json_info = json.loads(json_content)
            creds = Credentials.from_service_account_info(json_info, scopes=scopes)
        else:
            # Nạp từ file
            creds = Credentials.from_service_account_file(self.gsvc_json, scopes=scopes)
        
        self.gs_client = gspread.authorize(creds)
        self.gs_sheet = self.gs_client.open_by_key(self.gsheet_id)
    
    def backup_sheet(self, sheet_name: str, compress: bool = True) -> str:
        """
        Backup một sheet cụ thể
        
        Returns:
            Path to backup file
        """
        try:
            worksheet = self.gs_sheet.worksheet(sheet_name)
            data = worksheet.get_all_values()
            
            # Create backup filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{sheet_name}_{timestamp}.json"
            
            if compress:
                filename += ".gz"
            
            filepath = os.path.join(self.backup_dir, filename)
            
            # Save data
            backup_data = {
                "sheet_name": sheet_name,
                "timestamp": timestamp,
                "row_count": len(data),
                "data": data
            }
            
            if compress:
                with gzip.open(filepath, 'wt', encoding='utf-8') as f:
                    json.dump(backup_data, f, ensure_ascii=False, indent=2)
            else:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"Backed up {sheet_name} to {filepath}")
            return filepath
            
        except Exception as e:
            self.logger.error(f"Failed to backup {sheet_name}: {e}")
            raise
    
    def backup_all_sheets(self, compress: bool = True) -> List[str]:
        """
        Backup tất cả sheets
        
        Returns:
            List of backup file paths
        """
        worksheets = self.gs_sheet.worksheets()
        backup_files = []
        
        for ws in worksheets:
            try:
                filepath = self.backup_sheet(ws.title, compress=compress)
                backup_files.append(filepath)
            except Exception as e:
                self.logger.error(f"Failed to backup {ws.title}: {e}")
        
        self.logger.info(f"Backed up {len(backup_files)} sheets")
        return backup_files
    
    def restore_sheet(self, backup_file: str, sheet_name: Optional[str] = None):
        """
        Restore sheet từ backup file
        
        Args:
            backup_file: Path to backup file
            sheet_name: Target sheet name (nếu None, dùng tên trong backup)
        """
        try:
            # Load backup data
            if backup_file.endswith('.gz'):
                with gzip.open(backup_file, 'rt', encoding='utf-8') as f:
                    backup_data = json.load(f)
            else:
                with open(backup_file, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
            
            target_sheet = sheet_name or backup_data['sheet_name']
            data = backup_data['data']
            
            # Get or create worksheet
            try:
                worksheet = self.gs_sheet.worksheet(target_sheet)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = self.gs_sheet.add_worksheet(
                    title=target_sheet,
                    rows=len(data),
                    cols=len(data[0]) if data else 10
                )
            
            # Clear existing data
            worksheet.clear()
            
            # Restore data
            if data:
                worksheet.update(data, value_input_option='USER_ENTERED')
            
            self.logger.info(f"Restored {target_sheet} from {backup_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to restore from {backup_file}: {e}")
            raise
    
    def list_backups(self, sheet_name: Optional[str] = None) -> List[Dict]:
        """
        List tất cả backup files
        
        Args:
            sheet_name: Filter by sheet name (optional)
        
        Returns:
            List of backup info dicts
        """
        backups = []
        
        for filename in os.listdir(self.backup_dir):
            if not filename.endswith(('.json', '.json.gz')):
                continue
            
            # Parse filename
            parts = filename.replace('.json.gz', '').replace('.json', '').split('_')
            if len(parts) < 3:
                continue
            
            backup_sheet_name = '_'.join(parts[:-2])
            timestamp_str = f"{parts[-2]}_{parts[-1]}"
            
            # Filter by sheet name if specified
            if sheet_name and backup_sheet_name != sheet_name:
                continue
            
            filepath = os.path.join(self.backup_dir, filename)
            file_size = os.path.getsize(filepath)
            
            backups.append({
                'filename': filename,
                'filepath': filepath,
                'sheet_name': backup_sheet_name,
                'timestamp': timestamp_str,
                'size_bytes': file_size,
                'size_mb': round(file_size / (1024 * 1024), 2)
            })
        
        # Sort by timestamp descending
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return backups
    
    def cleanup_old_backups(self, days: int = 30, keep_minimum: int = 5):
        """
        Xóa backup cũ
        
        Args:
            days: Xóa backup cũ hơn X ngày
            keep_minimum: Giữ lại ít nhất X backup gần nhất cho mỗi sheet
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        
        # Group backups by sheet
        backups_by_sheet = {}
        for backup in self.list_backups():
            sheet = backup['sheet_name']
            if sheet not in backups_by_sheet:
                backups_by_sheet[sheet] = []
            backups_by_sheet[sheet].append(backup)
        
        deleted_count = 0
        
        for sheet, backups in backups_by_sheet.items():
            # Sort by timestamp descending
            backups.sort(key=lambda x: x['timestamp'], reverse=True)
            
            # Keep minimum recent backups
            keep_backups = backups[:keep_minimum]
            check_backups = backups[keep_minimum:]
            
            for backup in check_backups:
                # Parse timestamp
                try:
                    backup_date = datetime.strptime(
                        backup['timestamp'],
                        "%Y%m%d_%H%M%S"
                    )
                    
                    if backup_date < cutoff_date:
                        os.remove(backup['filepath'])
                        deleted_count += 1
                        self.logger.info(f"Deleted old backup: {backup['filename']}")
                        
                except Exception as e:
                    self.logger.error(f"Failed to delete {backup['filename']}: {e}")
        
        self.logger.info(f"Cleaned up {deleted_count} old backups")
        return deleted_count
    
    def export_to_csv(self, sheet_name: str, output_file: str):
        """Export sheet to CSV"""
        import csv
        
        try:
            worksheet = self.gs_sheet.worksheet(sheet_name)
            data = worksheet.get_all_values()
            
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(data)
            
            self.logger.info(f"Exported {sheet_name} to {output_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to export {sheet_name}: {e}")
            raise
    
    def import_from_csv(self, csv_file: str, sheet_name: str):
        """Import CSV to sheet"""
        import csv
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                data = list(reader)
            
            # Get or create worksheet
            try:
                worksheet = self.gs_sheet.worksheet(sheet_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = self.gs_sheet.add_worksheet(
                    title=sheet_name,
                    rows=len(data),
                    cols=len(data[0]) if data else 10
                )
            
            # Clear and update
            worksheet.clear()
            if data:
                worksheet.update(data, value_input_option='USER_ENTERED')
            
            self.logger.info(f"Imported {csv_file} to {sheet_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to import {csv_file}: {e}")
            raise
    
    def create_snapshot(self) -> str:
        """
        Tạo snapshot của toàn bộ spreadsheet
        
        Returns:
            Path to snapshot file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_file = os.path.join(
            self.backup_dir,
            f"snapshot_{timestamp}.json.gz"
        )
        
        # Backup all sheets
        all_data = {}
        for ws in self.gs_sheet.worksheets():
            all_data[ws.title] = ws.get_all_values()
        
        snapshot_data = {
            "timestamp": timestamp,
            "spreadsheet_id": self.gsheet_id,
            "spreadsheet_title": self.gs_sheet.title,
            "sheets": all_data
        }
        
        with gzip.open(snapshot_file, 'wt', encoding='utf-8') as f:
            json.dump(snapshot_data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"Created snapshot: {snapshot_file}")
        return snapshot_file
    
    def restore_snapshot(self, snapshot_file: str):
        """Restore từ snapshot"""
        try:
            with gzip.open(snapshot_file, 'rt', encoding='utf-8') as f:
                snapshot_data = json.load(f)
            
            for sheet_name, data in snapshot_data['sheets'].items():
                try:
                    worksheet = self.gs_sheet.worksheet(sheet_name)
                except gspread.exceptions.WorksheetNotFound:
                    worksheet = self.gs_sheet.add_worksheet(
                        title=sheet_name,
                        rows=len(data),
                        cols=len(data[0]) if data else 10
                    )
                
                worksheet.clear()
                if data:
                    worksheet.update(data, value_input_option='USER_ENTERED')
            
            self.logger.info(f"Restored snapshot from {snapshot_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to restore snapshot: {e}")
            raise


# ============= USAGE EXAMPLES =============

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize
    backup_manager = BackupManager(
        gsheet_id=os.getenv("GSHEET_ID"),
        gsvc_json=os.getenv("GSVC_JSON", "service_account.json")
    )
    
    # 1. Backup single sheet
    backup_manager.backup_sheet("ORDERS")
    
    # 2. Backup all sheets
    backup_manager.backup_all_sheets()
    
    # 3. List backups
    backups = backup_manager.list_backups()
    for backup in backups:
        print(f"{backup['filename']} - {backup['size_mb']} MB")
    
    # 4. Restore from backup
    # backup_manager.restore_sheet("ORDERS_20260510_120000.json.gz")
    
    # 5. Create snapshot
    backup_manager.create_snapshot()
    
    # 6. Cleanup old backups
    backup_manager.cleanup_old_backups(days=30, keep_minimum=5)
    
    # 7. Export to CSV
    backup_manager.export_to_csv("ORDERS", "orders_export.csv")

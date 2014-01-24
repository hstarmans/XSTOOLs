#!C:\WinPython\Python-2.7.5\python.exe
# -*- coding: utf-8 -*-
# **********************************************************************
#   This program is free software; you can redistribute it and/or
#   modify it under the terms of the GNU General Public License
#   as published by the Free Software Foundation; either version 2
#   of the License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
#   02111-1307, USA.
#
#   (c)2012 - X Engineering Software Systems Corp. (www.xess.com)
# **********************************************************************

import sys
import os
import xstools
import xstools.xsboard as XSBOARD
import xstools.xserror as XSERROR
import xstools_defs
import wx
import wx.lib
import wx.lib.intctrl as INTCTRL
import wx.lib.flatnotebook as FNB
import wx.lib.platebtn as PBTN
import wx.html
from pubsub import pub as PUBSUB
from threading import Thread


# ********************* Globals ***********************************
active_board = None
icon_dir = os.path.join(xstools.install_dir, 'icons')


# ===============================================================
# GXSTOOLs About Box.
# ===============================================================

class GxsHtmlWindow(wx.html.HtmlWindow):

    def __init__(self, parent, id, size=(600, 400),):
        super(GxsHtmlWindow, self).__init__(parent, id, size=size)
        if 'gtk2' in wx.PlatformInfo:
            self.SetStandardFonts()

    def OnLinkClicked(self, link):
        wx.LaunchDefaultBrowser(link.GetHref())


class GxsAboutBox(wx.Dialog):

    def __init__(self):
        super(GxsAboutBox, self).__init__(None, -1, 'About <<project>>',
                                          style=wx.DEFAULT_DIALOG_STYLE | wx.THICK_FRAME
                                          | wx.RESIZE_BORDER | wx.TAB_TRAVERSAL)
        hwin = GxsHtmlWindow(self, -1, size=(400, 200))
        aboutText = \
            """<p>Graphical XESS Tools Utility Version %s</p>"""
        hwin.SetPage(aboutText % xstools_defs.VERSION)
        btn = hwin.FindWindowById(wx.ID_OK)
        irep = hwin.GetInternalRepresentation()
        hwin.SetSize((irep.GetWidth() + 25, irep.GetHeight() + 10))
        self.SetClientSize(hwin.GetSize())
        self.CentreOnParent(wx.BOTH)
        self.SetFocus()


# ===============================================================
# Continually running timer that triggers periodic events.
# ===============================================================

class GxsTimer(wx.Timer):

    def __init__(self, *args, **kwargs):
        super(GxsTimer, self).__init__(*args, **kwargs)
        PUBSUB.subscribe(self.start, "Timer.Start")
        PUBSUB.subscribe(self.stop, "Timer.Stop")
        PUBSUB.sendMessage("Timer.Start")
        self.Start(milliseconds=100, oneShot=False)

    def start(self):
        self.Start(milliseconds=100, oneShot=False)

    def stop(self):
        self.Stop()

    def Notify(self):
        PUBSUB.sendMessage("Port.Update")
        PUBSUB.sendMessage("Progress.Pulse")


# ===============================================================
# Status bar.
# ===============================================================

class GxsStatusBar(wx.StatusBar):
    fields = ("Port", "Board", )

    def __init__(self, *args, **kwargs):
        super(GxsStatusBar, self).__init__(*args, **kwargs)
        self.SetFieldsCount(len(self.fields))
        PUBSUB.subscribe(self.on_port_change, "Status.Port")
        PUBSUB.subscribe(self.on_board_change, "Status.Board")

    def on_port_change(self, port):
        self.change_status_bar(self.fields[0], port)

    def on_board_change(self, board):
        self.change_status_bar(self.fields[1], board)
        
    def change_status_bar(self, label, value):
        self.SetStatusText("%s: %s" % (label,value), self.fields.index(label))


# ===============================================================
# Progress dialog for long-running stuff.
# ===============================================================

class GxsProgressDialog(wx.ProgressDialog):

    def __init__(self, *args, **kwargs):
        self._value = 0
        if 'style' not in kwargs:
            kwargs['style'] = wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE | wx.PD_SMOOTH
        if 'message' not in kwargs:
            kwargs['message'] = " " * 80  # This sets the width of the progress window.
        if 'maximum' not in kwargs:
            kwargs['maximum'] = 100
        PUBSUB.subscribe(self.on_phase_change, "Progress.Phase")
        PUBSUB.subscribe(self.on_progress_change, "Progress.Pct")
        PUBSUB.subscribe(self.on_pulse, "Progress.Pulse")
        super(GxsProgressDialog, self).__init__(*args, **kwargs)

    def Destroy(self, *args, **kwargs):
        PUBSUB.unsubscribe(self.on_phase_change, "Progress.Phase")
        PUBSUB.unsubscribe(self.on_progress_change, "Progress.Pct")
        PUBSUB.unsubscribe(self.on_pulse, "Progress.Pulse")
        wx.ProgressDialog.Destroy(self)

    def on_phase_change(self, phase):
        if not self.Update(value=self._value, newmsg=phase)[0]:
            self.close()

    def on_progress_change(self, value):
        self._value = msg
        if not self.Update(value=value)[0]:
            self.close()

    def on_pulse(self):
        if not self.Pulse()[0]:
            self.close()
            
    def close(self):
        active_board.xsusb.terminate = True
        self.Destroy()


# ===============================================================
# Port setup panel.
# ===============================================================

class GxsPortPanel(wx.Panel):

    def __init__(self, *args, **kwargs):
        super(GxsPortPanel, self).__init__(*args, **kwargs)

        global active_board
        active_board = None

        self.SetToolTipString("Use this tab to select the port your XESS board is attached to.")

        self._port_list = wx.Choice(self)
        self._port_list.SetSelection(0)
        self._port_list.SetToolTipString('Select a port with an attached XESS board')
        self._port_list.Bind(wx.EVT_CHOICE, self.on_port_change)

        self._blink_button = wx.Button(self, label='Blink')
        self._blink_button.SetToolTipString('Click to blink LED on the board attached to the selected port')
        self._blink_button.Bind(wx.EVT_BUTTON, self.on_blink)
        self._blink_button.Disable()

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.AddSpacer(5)
        hsizer.Add(wx.StaticText(self, label='Port:'), 0,
                   wx.ALIGN_CENTER_VERTICAL)
        hsizer.Add(self._port_list, 0, wx.ALIGN_CENTER_VERTICAL)
        hsizer.AddSpacer(5)
        hsizer.Add(self._blink_button, 0, wx.ALIGN_CENTER_VERTICAL)
        hsizer.AddSpacer(5)

        vsizer = wx.BoxSizer(wx.VERTICAL)
        vsizer.AddSpacer(5)
        vsizer.Add(hsizer)
        vsizer.AddSpacer(5)

        self.SetSizer(vsizer)

        PUBSUB.subscribe(self.update_port_connections, "Port.Update")

    def update_port_connections(self):
        global active_board
        xsusb_ports = XSBOARD.XsUsb.get_xsusb_ports()
        num_boards = len(xsusb_ports)
        #print "# boards = %d" % num_boards
        if num_boards != self._port_list.GetCount():
            if num_boards == 0:
                # print "active board = ", str(active_board)
                # if active_board is not None:
                    # active_board.xsusb.disconnect()
                self._port_list.Clear()
                active_board = None
                wx.PostEvent(self._port_list, wx.PyCommandEvent(wx.EVT_CHOICE.typeId, wx.ID_ANY))
            else:
                ports = []
                for i in range(0, num_boards):
                    ports.append('USB%d' % i)
                self._port_list.Clear()
                self._port_list.AppendItems(ports)
                if active_board is None:
                    self._port_list.SetSelection(0)
                else:
                    xsusb_id = active_board.get_xsusb_id()
                    if xsusb_id is None:
                        self._port_list.SetSelection(0)
                    else:
                        self._port_list.SetSelection(xsusb_id)
                active_board = XSBOARD.Xula(self._port_list.GetSelection())
                wx.PostEvent(self._port_list, wx.PyCommandEvent(wx.EVT_CHOICE.typeId, wx.ID_ANY))

    def on_port_change(self, event):
        global active_board
        port_id = self._port_list.GetSelection()
        if port_id != wx.NOT_FOUND:
            self._active_port_name = "USB%d" % port_id
            active_board = XSBOARD.XsBoard.get_xsboard(port_id)
            self._active_board_name = active_board.name
            self._blink_button.Enable()
        else:
            self._active_port_name = ""
            self._active_board_name = ""
            self._blink_button.Disable()
            active_board = None
        PUBSUB.sendMessage("Status.Port", port=self._active_port_name)
        PUBSUB.sendMessage("Status.Board", board=self._active_board_name)

    def on_blink(self, event):
        port_id = self._port_list.GetSelection()
        if port_id != wx.NOT_FOUND:
            active_board.get_board_info()


# ===============================================================
# Flash upload/download panel.
# ===============================================================

class GxsFlashPanel(wx.Panel):

    def __init__(self, *args, **kwargs):
        super(GxsFlashPanel, self).__init__(*args, **kwargs)

        mem_type = 'Flash'
        
        self.SetToolTipString('Use this tab to transfer data to/from the %s on your XESS board.' % mem_type)

        #file_wildcard = 'Intel Hex (*.hex)|*.hex|Motorola EXO (*.exo)|*.exo|XESS (*.xes)|*.xes'
        file_wildcard = 'Intel Hex (*.hex)|*.hex'

        self._dnld_file_picker = wx.FilePickerCtrl(self, wildcard=file_wildcard,
                                                   style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        self._dnld_file_picker.SetToolTipString('File to download to %s' % mem_type)
        self.Bind(wx.EVT_FILEPICKER_CHANGED, self.set_download_file, self._dnld_file_picker)
        self._upld_file_picker = wx.FilePickerCtrl(self, wildcard=file_wildcard,
                                                   style=wx.FLP_SAVE | wx.FLP_OVERWRITE_PROMPT | wx.FLP_USE_TEXTCTRL)
        self._upld_file_picker.SetToolTipString('File to upload from %s' % mem_type)
        self.Bind(wx.EVT_FILEPICKER_CHANGED, self.set_upload_file, self._upld_file_picker)

        down_arrow_bmp = wx.Bitmap(os.path.join(icon_dir,'down_arrow.png'), wx.BITMAP_TYPE_PNG)
        down_arrow_disabled_bmp = wx.Bitmap(os.path.join(icon_dir,'down_arrow_disabled.png'), wx.BITMAP_TYPE_PNG)
        self._dnld_button = PBTN.PlateButton(self)
        self._dnld_button.SetBitmap(down_arrow_bmp)
        self._dnld_button.SetBitmapDisabled(down_arrow_disabled_bmp)
        self._dnld_button.SetToolTipString('Start download to %s' % mem_type)
        self._dnld_button.Disable()
        self.Bind(wx.EVT_BUTTON, self.on_download, self._dnld_button)
        self._upld_button = PBTN.PlateButton(self)
        self._upld_button.SetBitmap(down_arrow_bmp)
        self._upld_button.SetBitmapDisabled(down_arrow_disabled_bmp)
        self._upld_button.SetToolTipString('Start upload from %s' % mem_type)
        self._upld_button.Disable()
        self.Bind(wx.EVT_BUTTON, self.on_upload, self._upld_button)

        self._erase_button = wx.Button(self, label='Erase')
        self._erase_button.SetToolTipString('Click to erase %s between the upper and lower addresses' % mem_type)
        self._erase_button.Bind(wx.EVT_BUTTON, self.on_erase)
        self._erase_button.Enable()

        self._hi_addr_ctrl = INTCTRL.IntCtrl(self)
        self._hi_addr_ctrl.SetToolTipString('Enter upper %s address here' % mem_type)
        self._lo_addr_ctrl = INTCTRL.IntCtrl(self)
        self._lo_addr_ctrl.SetToolTipString('Enter lower %s address here' % mem_type)
        addr_vsizer = wx.BoxSizer(wx.VERTICAL)
        addr_vsizer.Add(self._hi_addr_ctrl)
        addr_vsizer.Add(wx.StaticText(self, label='Upper Address'), 0, wx.CENTER)
        addr_vsizer.AddStretchSpacer()
        addr_vsizer.AddSpacer(10)
        addr_vsizer.Add(self._erase_button)
        addr_vsizer.AddSpacer(10)
        addr_vsizer.AddStretchSpacer()
        addr_vsizer.Add(wx.StaticText(self, label='Lower Address'), 0, wx.CENTER)
        addr_vsizer.Add(self._lo_addr_ctrl)
        chip_hsizer = wx.BoxSizer(wx.HORIZONTAL)
        flash_bmp = wx.Bitmap(os.path.join(icon_dir,'serial_flash.png'), wx.BITMAP_TYPE_PNG)
        flash_stbmp = wx.StaticBitmap(self, bitmap=flash_bmp)
        chip_hsizer.Add(flash_stbmp)
        chip_hsizer.AddSpacer(5)
        chip_hsizer.Add(addr_vsizer, 1, wx.ALIGN_CENTER)

        vsizer = wx.BoxSizer(wx.VERTICAL)
        vsizer.AddSpacer(5)
        vsizer.Add(self._dnld_file_picker, 0, wx.EXPAND)
        vsizer.Add(self._dnld_button, 0, wx.ALIGN_CENTER)
        vsizer.Add(chip_hsizer, 0, wx.ALIGN_CENTER)
        vsizer.Add(self._upld_button, 0, wx.ALIGN_CENTER)
        vsizer.Add(self._upld_file_picker, 0, wx.EXPAND)
        vsizer.AddSpacer(5)

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.AddSpacer(5)
        chip_hsizer.Hide(addr_vsizer)
        hsizer.Add(vsizer, 1, wx.GROW)
        chip_hsizer.Show(addr_vsizer)
        hsizer.AddSpacer(5)

        self.SetSizer(hsizer)

    def set_download_file(self, event):
        if event.GetEventObject().GetPath():
            self._dnld_button.Enable()
        else:
            self._dnld_button.Disable()

    def on_download(self, event):
        PUBSUB.subscribe(self.cleanup, "Flash.Cleanup")
        self._progress = GxsProgressDialog(title="Downloading to Flash", parent=self)
        GxsFlashDownloadThread(self._dnld_file_picker.GetPath())

    def set_upload_file(self, event):
        if event.GetEventObject().GetPath():
            self._upld_button.Enable()
        else:
            self._upld_button.Disable()

    def on_upload(self, event):
        PUBSUB.subscribe(self.cleanup, "Flash.Cleanup")
        self._progress = GxsProgressDialog(title="Uploading from Flash", parent=self)
        GxsFlashUploadThread(self._upld_file_picker.GetPath(), self._lo_addr_ctrl.GetValue(), self._hi_addr_ctrl.GetValue())
        
    def on_erase(self, event):
        PUBSUB.subscribe(self.cleanup, "Flash.Cleanup")
        self._progress = GxsProgressDialog(title="Erasing Flash", parent=self)
        GxsFlashEraseThread(self._lo_addr_ctrl.GetValue(), self._hi_addr_ctrl.GetValue())

    def cleanup(self):
        PUBSUB.unsubscribe(self.cleanup, "Flash.Cleanup")
        self._progress.Destroy()


# ===============================================================
# Thread for running Flash download operation.
# ===============================================================
class GxsFlashDownloadThread(Thread):

    def __init__(self, dnld_file):
        Thread.__init__(self)
        self._dnld_file = dnld_file
        self.start()

    def run(self):
        msg_box_title = 'Flash Download Result'
        try:
            active_board.write_cfg_flash(self._dnld_file)
        except XSERROR.XsTerminate as e:
            PUBSUB.sendMessage("Flash.Cleanup")
            wx.MessageBox('Cancelled.', msg_box_title, wx.OK | wx.ICON_INFORMATION)
            return
        except XSERROR.XsError as e:
            PUBSUB.sendMessage("Flash.Cleanup")
            wx.MessageBox(str(e), msg_box_title, wx.OK | wx.ICON_ERROR)
            return
        PUBSUB.sendMessage("Flash.Cleanup")
        wx.MessageBox('Success!', msg_box_title, wx.OK | wx.ICON_INFORMATION)


# ===============================================================
# Thread for running Flash upload operation.
# ===============================================================
class GxsFlashUploadThread(Thread):

    def __init__(self, upld_file, low_addr, high_addr):
        Thread.__init__(self)
        self._upld_file = upld_file
        self._low_addr = low_addr
        self._high_addr = high_addr
        self.start()

    def run(self):
        msg_box_title = 'Flash Upload Result'
        try:
            active_board.read_cfg_flash(self._low_addr, self._high_addr).tofile(self._upld_file, format='hex')
        except XSERROR.XsTerminate as e:
            PUBSUB.sendMessage("Flash.Cleanup")
            wx.MessageBox('Cancelled.', msg_box_title, wx.OK | wx.ICON_INFORMATION)
            return
        except XSERROR.XsError as e:
            PUBSUB.sendMessage("Flash.Cleanup")
            wx.MessageBox(str(e), msg_box_title, wx.OK | wx.ICON_ERROR)
            return
        PUBSUB.sendMessage("Flash.Cleanup")
        wx.MessageBox('Success!', msg_box_title, wx.OK | wx.ICON_INFORMATION)


# ===============================================================
# Thread for running Flash erase operation.
# ===============================================================
class GxsFlashEraseThread(Thread):

    def __init__(self, low_addr, high_addr):
        Thread.__init__(self)
        self._low_addr = low_addr
        self._high_addr = high_addr
        self.start()

    def run(self):
        msg_box_title = 'Flash Erase Result'
        try:
            active_board.erase_cfg_flash(self._low_addr, self._high_addr)
        except XSERROR.XsTerminate as e:
            PUBSUB.sendMessage("Flash.Cleanup")
            wx.MessageBox('Cancelled.', msg_box_title, wx.OK | wx.ICON_INFORMATION)
            return
        except XSERROR.XsError as e:
            PUBSUB.sendMessage("Flash.Cleanup")
            wx.MessageBox(str(e), msg_box_title, wx.OK | wx.ICON_ERROR)
            return
        PUBSUB.sendMessage("Flash.Cleanup")
        wx.MessageBox('Success!', msg_box_title, wx.OK | wx.ICON_INFORMATION)


# ===============================================================
# SDRAM upload/download panel.
# ===============================================================

class GxsSdramPanel(wx.Panel):

    def __init__(self, *args, **kwargs):
        super(GxsSdramPanel, self).__init__(*args, **kwargs)

        mem_type = 'SDRAM'
        
        self.SetToolTipString('Use this tab to transfer data to/from the %s on your XESS board.' % mem_type)

        #file_wildcard = 'Intel Hex (*.hex)|*.hex|Motorola EXO (*.exo)|*.exo|XESS (*.xes)|*.xes'
        file_wildcard = 'Intel Hex (*.hex)|*.hex'

        self._dnld_file_picker = wx.FilePickerCtrl(self, wildcard=file_wildcard,
                                                   style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        self._dnld_file_picker.SetToolTipString('File to download to %s' % mem_type)
        self.Bind(wx.EVT_FILEPICKER_CHANGED, self.set_download_file, self._dnld_file_picker)
        self._upld_file_picker = wx.FilePickerCtrl(self, wildcard=file_wildcard,
                                                   style=wx.FLP_SAVE | wx.FLP_OVERWRITE_PROMPT | wx.FLP_USE_TEXTCTRL)
        self._upld_file_picker.SetToolTipString('File to upload from %s' % mem_type)
        self.Bind(wx.EVT_FILEPICKER_CHANGED, self.set_upload_file, self._upld_file_picker)

        down_arrow_bmp = wx.Bitmap(os.path.join(icon_dir,'down_arrow.png'), wx.BITMAP_TYPE_PNG)
        down_arrow_disabled_bmp = wx.Bitmap(os.path.join(icon_dir,'down_arrow_disabled.png'), wx.BITMAP_TYPE_PNG)
        self._dnld_button = PBTN.PlateButton(self)
        self._dnld_button.SetBitmap(down_arrow_bmp)
        self._dnld_button.SetBitmapDisabled(down_arrow_disabled_bmp)
        self._dnld_button.SetToolTipString('Start download to %s' % mem_type)
        self._dnld_button.Disable()
        self.Bind(wx.EVT_BUTTON, self.on_download, self._dnld_button)
        self._upld_button = PBTN.PlateButton(self)
        self._upld_button.SetBitmap(down_arrow_bmp)
        self._upld_button.SetBitmapDisabled(down_arrow_disabled_bmp)
        self._upld_button.SetToolTipString('Start upload from %s' % mem_type)
        self._upld_button.Disable()
        self.Bind(wx.EVT_BUTTON, self.on_upload, self._upld_button)

        # self._erase_button = wx.Button(self, label='Erase')
        # self._erase_button.SetToolTipString('Click to erase memory between the upper and lower addresses')
        # self._erase_button.Bind(wx.EVT_BUTTON, self.on_erase)
        # self._erase_button.Enable()

        self._hi_addr_ctrl = INTCTRL.IntCtrl(self)
        self._hi_addr_ctrl.SetToolTipString('Enter upper %s address here' % mem_type)
        self._lo_addr_ctrl = INTCTRL.IntCtrl(self)
        self._lo_addr_ctrl.SetToolTipString('Enter lower %s address here' % mem_type)
        addr_vsizer = wx.BoxSizer(wx.VERTICAL)
        addr_vsizer.Add(self._hi_addr_ctrl)
        addr_vsizer.Add(wx.StaticText(self, label='Upper Address'), 0, wx.CENTER)
        #addr_vsizer.AddStretchSpacer()
        #addr_vsizer.Add(self._erase_button)
        addr_vsizer.AddStretchSpacer()
        addr_vsizer.Add(wx.StaticText(self, label='Lower Address'), 0, wx.CENTER)
        addr_vsizer.Add(self._lo_addr_ctrl)
        chip_hsizer = wx.BoxSizer(wx.HORIZONTAL)
        sdram_bmp = wx.Bitmap(os.path.join(icon_dir,'sdram.png'), wx.BITMAP_TYPE_PNG)
        sdram_stbmp = wx.StaticBitmap(self, bitmap=sdram_bmp)
        chip_hsizer.Add(sdram_stbmp)
        chip_hsizer.AddSpacer(5)
        chip_hsizer.Add(addr_vsizer, 1, wx.GROW)

        vsizer = wx.BoxSizer(wx.VERTICAL)
        vsizer.AddSpacer(5)
        vsizer.Add(self._dnld_file_picker, 0, wx.EXPAND)
        vsizer.Add(self._dnld_button, 0, wx.ALIGN_CENTER)
        vsizer.Add(chip_hsizer, 0, wx.ALIGN_CENTER)
        vsizer.Add(self._upld_button, 0, wx.ALIGN_CENTER)
        vsizer.Add(self._upld_file_picker, 0, wx.EXPAND)
        vsizer.AddSpacer(5)

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.AddSpacer(5)
        chip_hsizer.Hide(addr_vsizer)
        hsizer.Add(vsizer, 1, wx.GROW)
        chip_hsizer.Show(addr_vsizer)
        hsizer.AddSpacer(5)

        self.SetSizer(hsizer)

    def set_download_file(self, event):
        if event.GetEventObject().GetPath():
            self._dnld_button.Enable()
        else:
            self._dnld_button.Disable()

    def on_download(self, event):
        PUBSUB.subscribe(self.cleanup, "Sdram.Cleanup")
        self._progress = GxsProgressDialog(title="Downloading to SDRAM", parent=self)
        GxsSdramDownloadThread(self._dnld_file_picker.GetPath())

    def set_upload_file(self, event):
        if event.GetEventObject().GetPath():
            self._upld_button.Enable()
        else:
            self._upld_button.Disable()

    def on_upload(self, event):
        PUBSUB.subscribe(self.cleanup, "Sdram.Cleanup")
        self._progress = GxsProgressDialog(title="Uploading from SDRAM", parent=self)
        GxsSdramUploadThread(self._upld_file_picker.GetPath(), self._lo_addr_ctrl.GetValue(), self._hi_addr_ctrl.GetValue())
        
    def on_erase(self, event):
        PUBSUB.subscribe(self.cleanup, "Sdram.Cleanup")
        self._progress = GxsProgressDialog(title="Erasing SDRAM", parent=self)
        GxsSdramEraseThread(self._lo_addr_ctrl.GetValue(), self._hi_addr_ctrl.GetValue())

    def cleanup(self):
        PUBSUB.unsubscribe(self.cleanup, "Sdram.Cleanup")
        self._progress.Destroy()


# ===============================================================
# Thread for running SDRAM download operation.
# ===============================================================
class GxsSdramDownloadThread(Thread):

    def __init__(self, dnld_file):
        Thread.__init__(self)
        self._dnld_file = dnld_file
        self.start()

    def run(self):
        msg_box_title = 'SDRAM Download Result'
        try:
            active_board.write_sdram(self._dnld_file)
        except XSERROR.XsTerminate as e:
            PUBSUB.sendMessage("Sdram.Cleanup")
            wx.MessageBox('Cancelled.', msg_box_title, wx.OK | wx.ICON_INFORMATION)
            return
        except XSERROR.XsError as e:
            PUBSUB.sendMessage("Sdram.Cleanup")
            wx.MessageBox(str(e), msg_box_title, wx.OK | wx.ICON_ERROR)
            return
        PUBSUB.sendMessage("Sdram.Cleanup")
        wx.MessageBox('Success!', msg_box_title, wx.OK | wx.ICON_INFORMATION)


# ===============================================================
# Thread for running SDRAM upload operation.
# ===============================================================
class GxsSdramUploadThread(Thread):

    def __init__(self, upld_file, low_addr, high_addr):
        Thread.__init__(self)
        self._upld_file = upld_file
        self._low_addr = low_addr
        self._high_addr = high_addr
        self.start()

    def run(self):
        msg_box_title = 'SDRAM Upload Result'
        try:
            active_board.read_sdram(self._low_addr, self._high_addr).tofile(self._upld_file, format='hex')
        except XSERROR.XsTerminate as e:
            PUBSUB.sendMessage("Sdram.Cleanup")
            wx.MessageBox('Cancelled.', msg_box_title, wx.OK | wx.ICON_INFORMATION)
            return
        except XSERROR.XsError as e:
            PUBSUB.sendMessage("Sdram.Cleanup")
            wx.MessageBox(str(e), msg_box_title, wx.OK | wx.ICON_ERROR)
            return
        PUBSUB.sendMessage("Sdram.Cleanup")
        wx.MessageBox('Success!', msg_box_title, wx.OK | wx.ICON_INFORMATION)


# ===============================================================
# Thread for running SDRAM erase operation.
# ===============================================================
class GxsSdramEraseThread(Thread):

    def __init__(self, low_addr, high_addr):
        Thread.__init__(self)
        self._low_addr = low_addr
        self._high_addr = high_addr
        self.start()

    def run(self):
        msg_box_title = 'SDRAM Erase Result'
        try:
            active_board.erase_sdram(self._low_addr, self._high_addr)
        except XSERROR.XsTerminate as e:
            PUBSUB.sendMessage("Sdram.Cleanup")
            wx.MessageBox('Cancelled.', msg_box_title, wx.OK | wx.ICON_INFORMATION)
            return
        except XSERROR.XsError as e:
            PUBSUB.sendMessage("Sdram.Cleanup")
            wx.MessageBox(str(e), msg_box_title, wx.OK | wx.ICON_ERROR)
            return
        PUBSUB.sendMessage("Sdram.Cleanup")
        wx.MessageBox('Success!', msg_box_title, wx.OK | wx.ICON_INFORMATION)


# ===============================================================
# FPGA configuration panel.
# ===============================================================

class GxsFpgaConfigPanel(wx.Panel):

    def __init__(self, *args, **kwargs):
        super(GxsFpgaConfigPanel, self).__init__(*args, **kwargs)

        self.SetToolTipString("Use this tab to download bitstreams to the FPGA on your XESS board.")

        file_wildcard = 'Xilinx bitstreams (*.bit)|*.bit'

        self._bit_file_picker = wx.FilePickerCtrl(self, wildcard=file_wildcard,
                                                  style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        self._bit_file_picker.SetToolTipString('Bitstream file to download to FPGA')
        self.Bind(wx.EVT_FILEPICKER_CHANGED, self.set_bit_file, self._bit_file_picker)

        down_arrow_bmp = wx.Bitmap(os.path.join(icon_dir,'down_arrow.png'), wx.BITMAP_TYPE_PNG)
        down_arrow_disabled_bmp = wx.Bitmap(os.path.join(icon_dir,'down_arrow_disabled.png'), wx.BITMAP_TYPE_PNG)
        self._dnld_button = PBTN.PlateButton(self)
        self._dnld_button.SetBitmap(down_arrow_bmp)
        self._dnld_button.SetBitmapDisabled(down_arrow_disabled_bmp)
        self._dnld_button.SetToolTipString('Start download to FPGA')
        self._dnld_button.Disable()
        self.Bind(wx.EVT_BUTTON, self.on_config, self._dnld_button)

        fpga_bmp = wx.Bitmap(os.path.join(icon_dir,'fpga.png'), wx.BITMAP_TYPE_PNG)
        fpga_stbmp = wx.StaticBitmap(self, bitmap=fpga_bmp)

        vsizer = wx.BoxSizer(wx.VERTICAL)
        vsizer.AddSpacer(5)
        vsizer.Add(self._bit_file_picker, 0, wx.EXPAND)
        vsizer.Add(self._dnld_button, 0, wx.ALIGN_CENTER)
        vsizer.Add(fpga_stbmp, 0, wx.ALIGN_CENTER)
        vsizer.AddSpacer(5)

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.AddSpacer(5)
        hsizer.Add(vsizer, 1, wx.GROW)
        hsizer.AddSpacer(5)

        self.SetSizer(hsizer)

    def set_bit_file(self, event):
        if event.GetEventObject().GetPath():
            self._dnld_button.Enable()
        else:
            self._dnld_button.Disable()

    def on_config(self, event):
        PUBSUB.subscribe(self.cleanup, "Fpga.Cleanup")
        self._config_progress = GxsProgressDialog(title="Configure FPGA with Bitstream", parent=self)
        GxsFpgaConfigThread(self._bit_file_picker.GetPath())

    def cleanup(self):
        PUBSUB.unsubscribe(self.cleanup, "Fpga.Cleanup")
        self._config_progress.Destroy()


# ===============================================================
# Thread for running FPGA configuration.
# ===============================================================
class GxsFpgaConfigThread(Thread):

    def __init__(self, config_file):
        Thread.__init__(self)
        self._config_file = config_file
        self.start()

    def run(self):
        msg_box_title = 'FPGA Configuration Result'
        try:
            active_board.configure(self._config_file)
        except XSERROR.XsTerminate as e:
            PUBSUB.sendMessage("Fpga.Cleanup")
            wx.MessageBox('Cancelled.', msg_box_title, wx.OK | wx.ICON_INFORMATION)
            return
        except XSERROR.XsError as e:
            PUBSUB.sendMessage("Fpga.Cleanup")
            wx.MessageBox(str(e), msg_box_title, wx.OK | wx.ICON_ERROR)
            return
        PUBSUB.sendMessage("Fpga.Cleanup")
        wx.MessageBox('Success!', msg_box_title, wx.OK | wx.ICON_INFORMATION)


# ===============================================================
# Microcontroller panel.
# ===============================================================

class GxsMicrocontrollerPanel(wx.Panel):

    def __init__(self, *args, **kwargs):
        super(GxsMicrocontrollerPanel, self).__init__(*args, **kwargs)

        self.SetToolTipString("Use this tab to download new firmware to the microcontroller flash on your XESS board.")

        file_wildcard = 'object file (*.hex)|*.hex'

        self._obj_file_picker = wx.FilePickerCtrl(self,
                                                  wildcard=file_wildcard, style=wx.FLP_OPEN
                                                  | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        self._obj_file_picker.SetToolTipString('Hex object file to download to microcontroller')
        self.Bind(wx.EVT_FILEPICKER_CHANGED, self.set_obj_file,
                  self._obj_file_picker)

        down_arrow_bmp = wx.Bitmap(os.path.join(icon_dir,'down_arrow.png'), wx.BITMAP_TYPE_PNG)
        down_arrow_disabled_bmp = wx.Bitmap(os.path.join(icon_dir,'down_arrow_disabled.png'), wx.BITMAP_TYPE_PNG)
        self._dnld_button = PBTN.PlateButton(self)
        self._dnld_button.SetBitmap(down_arrow_bmp)
        self._dnld_button.SetBitmapDisabled(down_arrow_disabled_bmp)
        self._dnld_button.SetToolTipString('Start download to microcontroller flash')
        self._dnld_button.Disable()
        self.Bind(wx.EVT_BUTTON, self.on_update_firmware, self._dnld_button)

        uc_bmp = wx.Bitmap(os.path.join(icon_dir,'uC.png'), wx.BITMAP_TYPE_PNG)
        uc_stbmp = wx.StaticBitmap(self, bitmap=uc_bmp)

        vsizer = wx.BoxSizer(wx.VERTICAL)
        vsizer.AddSpacer(5)
        vsizer.Add(self._obj_file_picker, 0, wx.EXPAND)
        vsizer.Add(self._dnld_button, 0, wx.ALIGN_CENTER)
        vsizer.Add(uc_stbmp, 0, wx.ALIGN_CENTER)
        vsizer.AddSpacer(5)

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.AddSpacer(5)
        hsizer.Add(vsizer, 1, wx.GROW)
        hsizer.AddSpacer(5)

        self.SetSizer(hsizer)

    def set_obj_file(self, event):
        if event.GetEventObject().GetPath():
            self._dnld_button.Enable()
        else:
            self._dnld_button.Disable()

    def on_update_firmware(self, event):
        PUBSUB.subscribe(self.cleanup, "Micro.Cleanup")
        self._upd_fmw_progress = GxsProgressDialog(title="Update Microcontroller Flash", parent=self)
        PUBSUB.sendMessage("Timer.Stop")
        GxsMicrocontrollerThread(self._obj_file_picker.GetPath())

    def cleanup(self):
        PUBSUB.unsubscribe(self.cleanup, "Micro.Cleanup")
        self._upd_fmw_progress.Destroy()
        # PUBSUB.sendMessage("Timer.Start")


# ===============================================================
# Thread for running uC firmware update.
# ===============================================================
class GxsMicrocontrollerThread(Thread):

    def __init__(self, fmw_obj_file):
        Thread.__init__(self)
        self._fmw_obj_file = fmw_obj_file
        self.start()

    def run(self):
        msg_box_title = 'Microcontroller Flash Update Result'
        try:
            active_board.update_firmware(self._fmw_obj_file)
        except XSERROR.XsTerminate as e:
            PUBSUB.sendMessage("Micro.Cleanup")
            wx.MessageBox('Cancelled.', msg_box_title, wx.OK | wx.ICON_INFORMATION)
            return
        except XSERROR.XsError as e:
            PUBSUB.sendMessage("Micro.Cleanup")
            wx.MessageBox(str(e), msg_box_title, wx.OK | wx.ICON_ERROR)
            return
        PUBSUB.sendMessage("Micro.Cleanup")
        wx.MessageBox('Success!', msg_box_title, wx.OK | wx.ICON_INFORMATION)


# ===============================================================
# Board test diagnostic panel.
# ===============================================================

class GxsBoardTestPanel(wx.Panel):

    def __init__(self, *args, **kwargs):
        super(GxsBoardTestPanel, self).__init__(*args, **kwargs)

        self.SetToolTipString("Use this tab to run a diagnostic on your XESS board.")

        self._test_button = wx.Button(self, label='Test')
        self._test_button.SetToolTipString('Click to test the board attached to the selected port')
        self._test_button.Bind(wx.EVT_BUTTON, self.on_test)
        self._test_button.Disable()

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.AddSpacer(5)
        hsizer.Add(self._test_button, 0, wx.ALIGN_CENTER_VERTICAL)
        hsizer.AddSpacer(5)

        vsizer = wx.BoxSizer(wx.VERTICAL)
        vsizer.AddSpacer(5)
        vsizer.Add(hsizer)
        vsizer.AddSpacer(5)

        self.SetSizer(vsizer)

        PUBSUB.subscribe(self.update_port_connections, "Status.Board")

    def update_port_connections(self, board):
        if board is None or board == "":
            self._test_button.Disable()
        else:
            self._test_button.Enable()

    def on_test(self, event):
        PUBSUB.subscribe(self.cleanup, "Test.Cleanup")
        self._test_progress = GxsProgressDialog(title="Run Board Diagnostic", parent=self)
        GxsTestThread()

    def cleanup(self):
        PUBSUB.unsubscribe(self.cleanup, "Test.Cleanup")
        self._test_progress.Destroy()


# ===============================================================
# Thread for running board diagnostic.
# ===============================================================

class GxsTestThread(Thread):

    def __init__(self):
        Thread.__init__(self)
        self.start()

    def run(self):
        msg_box_title = 'Board Diagnostic Result'
        try:
            active_board.do_self_test()
        except XSERROR.XsTerminate as e:
            PUBSUB.sendMessage("Test.Cleanup")
            wx.MessageBox('Cancelled.', msg_box_title, wx.OK | wx.ICON_INFORMATION)
            return
        except XSERROR.XsError as e:
            PUBSUB.sendMessage("Test.Cleanup")
            wx.MessageBox(str(e), msg_box_title, wx.OK | wx.ICON_ERROR)
            return
        PUBSUB.sendMessage("Test.Cleanup")
        wx.MessageBox('Success!', msg_box_title, wx.OK | wx.ICON_INFORMATION)


# ===============================================================
# Board flags panel.
# ===============================================================

class GxsBoardFlagsPanel(wx.Panel):

    def __init__(self, *args, **kwargs):
        super(GxsBoardFlagsPanel, self).__init__(*args, **kwargs)

        self.SetToolTipString("Use this tab to set the flag bits in your XESS board.")

        self._aux_jtag_flag = wx.CheckBox(self, label='Enable auxiliary JTAG header')
        self._aux_jtag_flag.SetToolTipString('Check to enable the auxiliary JTAG interface through the four-pin header')
        self._aux_jtag_flag.Bind(wx.EVT_CHECKBOX, self.on_aux_jtag)
        #self._aux_jtag_flag.SetValue(active_board.get_aux_jtag_flag())
        self._aux_jtag_flag.Enable()

        self._flash_flag = wx.CheckBox(self, label='Enable FPGA access to the configuration flash')
        self._flash_flag.SetToolTipString('Check to allow the FPGA to read/write the configuration flash')
        self._flash_flag.Bind(wx.EVT_CHECKBOX, self.on_flash)
        #self._flash_flag.SetValue(active_board.get_flash_flag())
        self._flash_flag.Enable()

        vsizer = wx.BoxSizer(wx.VERTICAL)
        vsizer.AddSpacer(5)
        vsizer.Add(self._aux_jtag_flag, 0, wx.ALIGN_CENTER_VERTICAL)
        vsizer.AddSpacer(5)
        vsizer.Add(self._flash_flag, 0, wx.ALIGN_CENTER_VERTICAL)
        vsizer.AddSpacer(5)

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.AddSpacer(5)
        hsizer.Add(vsizer, 0, wx.ALIGN_TOP)
        hsizer.AddSpacer(5)

        self.SetSizer(hsizer)

        PUBSUB.subscribe(self.update_port_connections, "Status.Board")

    def update_port_connections(self, board):
        self._aux_jtag_flag.Enable()
        self._flash_flag.Enable()

    def on_aux_jtag(self, event):
        new_value = active_board.toggle_aux_jtag_flag()
        self._aux_jtag_flag.SetValue(new_value)

    def on_flash(self, event):
        new_value = active_board.toggle_flash_flag()
        self._flash_flag.SetValue(new_value)


# ===============================================================
# GXSTOOLs FlatNotebook for holding tabs.
# ===============================================================
class GxsFlatNotebook(FNB.FlatNotebook):

    def __init__(self, parent):
        mystyle = FNB.FNB_FF2 | FNB.FNB_NO_X_BUTTON | FNB.FNB_NO_NAV_BUTTONS | FNB.FNB_SMART_TABS
        super(GxsFlatNotebook, self).__init__(parent, style=mystyle)
        self._port_panel = GxsPortPanel(self)
        self._fpga_panel = GxsFpgaConfigPanel(self)
        self._uc_panel = GxsMicrocontrollerPanel(self)
        self._sdram_panel = GxsSdramPanel(self)
        self._flash_panel = GxsFlashPanel(self)
        self._test_panel = GxsBoardTestPanel(self)
        #self._flags_panel = GxsBoardFlagsPanel(self)
        self.AddPage(self._port_panel, 'Ports')
        self.AddPage(self._fpga_panel, 'FPGA')
        self.AddPage(self._flash_panel, 'Flash')
        self.AddPage(self._sdram_panel, 'SDRAM')
        self.AddPage(self._uc_panel, 'uC')
        self.AddPage(self._test_panel, 'Test')
        #self.AddPage(self._flags_panel, 'Flags')


class MyFrame(wx.Frame):

    def __init__(self, parent, id=wx.ID_ANY, title='', pos=wx.DefaultPosition,
                 size=(600,400), style=wx.DEFAULT_FRAME_STYLE, name='MyFrame',):
        super(MyFrame, self).__init__(parent, id, title, pos, size, style, name,)

        self.menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        # file_menu.Append(wx.ID_NEW)
        # file_menu.Append(wx.ID_OPEN)
        # file_menu.Append(wx.ID_SAVE)
        # file_menu.Append(wx.ID_SAVEAS)
        # file_menu.Append(wx.ID_CLOSE)
        m_exit = file_menu.Append(wx.ID_EXIT, 'E&xit\tAlt-X', 'Close window and exit program.')
        self.Bind(wx.EVT_MENU, self.on_exit, m_exit)
        self.menu_bar.Append(file_menu, 'File')

        help_menu = wx.Menu()
        # help_menu.Append(wx.ID_HELP)
        m_about = help_menu.Append(wx.ID_ABOUT)
        self.Bind(wx.EVT_MENU, self.on_about, m_about)
        self.menu_bar.Append(help_menu, 'Help')
        self.SetMenuBar(self.menu_bar)

        self.SetStatusBar(GxsStatusBar(self))
        
    def on_exit(self, event):
        self.Close()

    def on_about(self, event):
        dlg = GxsAboutBox()
        dlg.ShowModal()
        dlg.Destroy()


class MyApp(wx.App):

    def OnInit(self):
        self.frame = MyFrame(None, title='XESS Board Tools')
        self.notebook = GxsFlatNotebook(self.frame)
        self.SetTopWindow(self.frame)
        self.frame.Show()
        self.timer = GxsTimer()
        return True


if __name__ == '__main__':
    app = MyApp(False)
    app.MainLoop()

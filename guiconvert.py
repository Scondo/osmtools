'''
Created on 31.08.2013

@author: scond_000
'''
import wx
import wx.combo as combo
import wx.gizmos as gizmos
import subprocess
import logging
import gzip
import os.path

app = wx.App()


class CropCfg(wx.Panel):
    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)


class FileSelectorCombo(combo.ComboCtrl):
    def __init__(self, *args, **kw):
        combo.ComboCtrl.__init__(self, *args, **kw)
        bmp = wx.ArtProvider.GetBitmap(wx.ART_FILE_OPEN, wx.ART_MENU, (16, 16))
        # and tell the ComboCtrl to use it
        self.SetButtonBitmaps(bmp, True)

    # Overridden from ComboCtrl, called when the combo button is clicked
    def OnButtonClick(self):
        path = ""
        name = ""
        if self.GetValue():
            path, name = os.path.split(self.GetValue())

        dlg = wx.FileDialog(self, "Choose File", path, name,
                            "All files (*.*)|*.*",
                            wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() == wx.ID_OK:
            self.SetValue(dlg.GetPath())
        dlg.Destroy()
        self.GetParent().OnFileChange(None)
        self.SetFocus()

    # Overridden from ComboCtrl to avoid assert since there is no ComboPopup
    def DoSetPopupControl(self, popup):
        pass


class ResultCfg(wx.Panel):
    def OnFileChange(self, event):
        self.SetConfigByExt(self.filsel.GetValue())

    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)
        self._changefile = False
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.file = wx.BoxSizer(wx.HORIZONTAL)
        self.flbl = wx.StaticText(self, label="Select output file")
        self.filsel = FileSelectorCombo(self)
        self.Bind(wx.EVT_TEXT, self.OnFileChange, self.filsel)

        self.file.Add(self.flbl, flag=wx.ALL, border=3)
        self.file.Add(self.filsel, 1)
        self.fmt = wx.RadioBox(self, choices=["o5m", "pbf", "osm", "o5h"],
                               style=wx.RA_VERTICAL, label="File format")
        self.gzcb = wx.CheckBox(self, label="Compress with gzip")
        self.sizer.Add(self.file, 0, flag=wx.EXPAND)
        self.sizer.AddSpacer(5)
        self.sizer.Add(self.fmt)
        self.sizer.AddSpacer(5)
        self.sizer.Add(self.gzcb)
        self.SetSizer(self.sizer)

    def SetConfigByExt(self, filename=''):
        if filename.endswith('.gz'):
            self.gzcb.SetValue(True)
            filename = filename[:-3]

        if filename.endswith('.o5m'):
            self.fmt.SetSelection(0)
        elif filename.endswith('.pbf'):
            self.fmt.SetSelection(1)
        elif filename.endswith('.osm'):
            self.fmt.SetSelection(2)
        elif filename.endswith('.osh'):
            self.fmt.SetSelection(3)

    @property
    def ext4cfg(self):
        if self.fmt.GetSelection() == 0:
            ext = "o5m"
        elif self.fmt.GetSelection() == 1:
            ext = "pbf"
        elif self.fmt.GetSelection() == 2:
            ext = "osm"
        elif self.fmt.GetSelection() == 3:
            ext = "osh"

        if self.gzcb.IsChecked():
            ext = ext + ".gz"
        return ext

    def UpdateExt(self):
        filename = self.filsel.GetValue()
        if filename.endswith('.gz'):
            filename = filename[:-3]
        filename = os.path.splitext(filename)[0]
        self.filsel.SetValue('.'.join((filename, self.ext4cfg)))

    @property
    def changefile(self):
        return self._changefile

    @changefile.setter
    def changefile(self, value):
        self._changefile = value


class SourceCfg(wx.Panel):
    def upd_item(self, old=''):
        dlg = wx.FileDialog(self, "Choose File", '', old,
                            "All files (*.*)|*.*",
                            wx.FD_OPEN + wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            return dlg.GetPath()

    def new_item(self, event):
        it = self.upd_item()
        self._inlist.InsertStringItem(0, it)

    def edit_item(self, event):
        last = self._inlist.GetItemCount()
        i = event.GetIndex()
        if i + 1 <= last:
            return
        it = self._inlist.GetItemText(i)
        it = self.upd_item(it)
        if it is not None:
            self._inlist.SetItemText(i, it)

    def evt_test(self, event):
        logging.warn(event)

    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)
        self.inlist = gizmos.EditableListBox(self, -1, "Source files", (0, 0),
                                             (200, 150),
                                             style=gizmos.EL_ALLOW_DELETE +\
                                             gizmos.EL_ALLOW_NEW)
        self._inlist = self.inlist.GetListCtrl()
        self._newbtn = self.inlist.GetNewButton()
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.edit_item, self._inlist)
        self._newbtn.Bind(wx.EVT_BUTTON, self.new_item, self._newbtn)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.inlist, 1, flag=wx.EXPAND)
        self.mrg = wx.CheckBox(self, label="Merge revisions")
        self.sizer.AddSpacer(5)
        self.sizer.Add(self.mrg)
        self.SetSizer(self.sizer)


class Window(wx.Frame):
    def __init__(self, parent, title):
        wx.Frame.__init__(self, parent, title=title)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.config = wx.Notebook(self, style=wx.NB_TOP)
        self.source = SourceCfg(self.config)
        self.config.AddPage(self.source, "Source")
        self.result = ResultCfg(self.config)
        self.config.AddPage(self.result, "Result")

        self.crop = CropCfg(self.config)
        self.config.AddPage(self.crop, "Crop")
        self.gopanel = wx.Panel(self)
        self.sizer.Add(self.config, 1, flag=wx.EXPAND)
        self.sizer.Add(self.gopanel, flag=wx.ALL + wx.EXPAND)
        self.gobtn = wx.Button(self.gopanel, label="Convert")
        self.SetSizer(self.sizer)
        #self.SetAutoLayout(1)
        self.sizer.Fit(self)


if __name__ == "__main__":
    wnd = Window(None, "OsmConvert")
    wnd.Show(True)
    app.MainLoop()

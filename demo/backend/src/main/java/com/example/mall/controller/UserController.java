package com.example.mall.controller;

import com.example.mall.dto.ChangePasswordRequest;
import com.example.mall.dto.UpdateProfileRequest;
import com.example.mall.entity.User;
import com.example.mall.service.UserService;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

/**
 * 用户资料控制器(需登录):
 * PUT /api/users/profile   修改昵称/手机号
 * PUT /api/users/password  修改密码(需校验原密码)
 */
@RestController
@RequestMapping("/api/users")
public class UserController {

    private final UserService userService;

    @Autowired
    public UserController(UserService userService) {
        this.userService = userService;
    }

    @PutMapping("/profile")
    public User updateProfile(@RequestAttribute("userId") Long userId,
                              @Valid @RequestBody UpdateProfileRequest req) {
        return userService.updateProfile(userId, req.getNickname(), req.getPhone());
    }

    @PutMapping("/password")
    public User changePassword(@RequestAttribute("userId") Long userId,
                               @Valid @RequestBody ChangePasswordRequest req) {
        return userService.changePassword(userId, req.getOldPassword(), req.getNewPassword());
    }
}

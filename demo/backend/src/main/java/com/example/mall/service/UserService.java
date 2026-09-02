package com.example.mall.service;

import com.example.mall.entity.User;
import com.example.mall.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

/**
 * 用户服务:注册、登录校验、用户查询。
 * 密码使用 BCrypt 加密存储。
 */
@Service
public class UserService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Autowired
    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    /** 注册(默认普通用户,初始积分 0) */
    public User register(String username, String email, String password) {
        String normalizedEmail = email.toLowerCase().trim();
        if (userRepository.findByEmail(normalizedEmail) != null) {
            throw new IllegalArgumentException("该邮箱已注册");
        }
        User user = new User();
        user.setUsername(username.trim());
        user.setEmail(normalizedEmail);
        user.setNickname(username.trim());
        user.setPasswordHash(passwordEncoder.encode(password));
        user.setRole("USER");
        user.setPoints(0);
        Long id = userRepository.insert(user);
        User saved = userRepository.findById(id);
        return saved != null ? saved : user;
    }

    /** 登录校验,成功返回用户 */
    public User login(String email, String password) {
        User user = userRepository.findByEmail(email.toLowerCase().trim());
        if (user == null || !passwordEncoder.matches(password, user.getPasswordHash())) {
            throw new IllegalArgumentException("邮箱或密码错误");
        }
        return user;
    }

    public User getById(Long id) {
        return userRepository.findById(id);
    }

    /** 修改个人资料(昵称/手机号),返回最新用户 */
    public User updateProfile(Long id, String nickname, String phone) {
        User user = userRepository.findById(id);
        if (user == null) {
            throw new IllegalArgumentException("用户不存在");
        }
        userRepository.updateProfile(id, nickname.trim(), phone == null ? null : phone.trim());
        return userRepository.findById(id);
    }

    /** 修改密码:校验旧密码后更新 */
    public User changePassword(Long id, String oldPassword, String newPassword) {
        User user = userRepository.findById(id);
        if (user == null) {
            throw new IllegalArgumentException("用户不存在");
        }
        if (!passwordEncoder.matches(oldPassword, user.getPasswordHash())) {
            throw new IllegalArgumentException("原密码不正确");
        }
        userRepository.updatePassword(id, passwordEncoder.encode(newPassword));
        return userRepository.findById(id);
    }
}
